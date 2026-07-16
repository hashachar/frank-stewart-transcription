import os
import json
import time
import random
import base64
import argparse
import datetime
from pathlib import Path
from dotenv import load_dotenv
import openai
from openai import OpenAI

load_dotenv()

# max_retries=0 — ZERO automatic retries (explicit user requirement). A failed
# request (including a Flex "resource unavailable" 429) raises immediately and is
# NOT silently re-run, so we never pay for anything beyond the single request we
# issued. Any retry is a manual, deliberate decision.
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=1800.0, max_retries=0)

BASE        = Path(__file__).resolve().parent.parent
PROMPT_DIR  = BASE / "prompt"
SCANS_DIR   = BASE / "scans"
LOGS_DIR    = BASE / "logs"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".gif"}
MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff", ".tiff": "image/tiff",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# Pricing per 1M tokens (standard rates)
MODEL_PRICING = {
    "gpt-5.6-sol":   (5.00,  30.00),
    "gpt-5.6-terra": (2.50,  15.00),
    "gpt-5.6-luna":  (1.00,   6.00),
    "gpt-5.5":     (5.00,  30.00),
    "gpt-5.4":     (2.50,  15.00),
    "gpt-5.4-pro": (2.50,  15.00),
    "gpt-5.2":     (2.50,  15.00),
    "gpt-5.1":     (2.50,  15.00),
    "gpt-4.1":     (2.00,   8.00),
}

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--effort",  default="high", choices=["none", "low", "medium", "high", "xhigh"],
                    help="Reasoning effort (default: high)")
    ap.add_argument("--no-ci",   action="store_true",
                    help="Disable Code Interpreter")
    ap.add_argument("--flex",    action="store_true",
                    help="Use the Flex processing tier (service_tier=flex): ~50%% cheaper, "
                         "variable latency, may 429 'resource unavailable' under load")
    ap.add_argument("--flex-max-attempts", type=int, default=6,
                    help="Max attempts when Flex returns a 429 no-capacity rejection. Those "
                         "rejections are NOT executed and NOT billed, so retrying them is free; "
                         "we back off exponentially between them. Only 429s are retried — any "
                         "other error raises immediately so we never re-run billable work "
                         "(default: 6; use 1 to disable)")
    ap.add_argument("--outdir",  type=Path, default=None,
                    help="Output subfolder under outputs/ (default: auto-named)")
    ap.add_argument("--image",   type=str, default=None,
                    help="Image filename (with or without extension) in the scans folder (default: first file found)")
    ap.add_argument("--model",          type=str, default="gpt-5.5",
                    help="OpenAI model to use (default: gpt-5.5)")
    ap.add_argument("--max-tool-calls", type=int, default=None,
                    help="Cap the number of Code Interpreter calls per response (default: unlimited)")
    ap.add_argument("--prompt", type=str, default=None,
                    help="Prompt filename stem or prefix (e.g. 'Phase 1e') in the prompt folder (default: first file found)")
    return ap.parse_args()


def _create_with_flex_backoff(create_kwargs, max_attempts, base_delay=15.0, max_delay=120.0):
    """Issue one Responses request, retrying ONLY on a 429 'resource unavailable'
    (Flex has no capacity right now). Those 429s are rejected before the model runs,
    so they are NOT billed — retrying them is free. Any OTHER error (a 5xx that may
    have executed, a timeout, a 400 bad request) is raised immediately: we never
    re-run something that could have been billed. Returns (response, n_attempts)."""
    last = None
    for attempt in range(1, max_attempts + 1):
        try:
            return client.responses.create(**create_kwargs), attempt
        except openai.RateLimitError as exc:      # 429 — not executed, not billed
            last = exc
            if attempt == max_attempts:
                break
            # Respect a Retry-After header if the 429 carries one, else exp. backoff.
            retry_after = None
            try:
                hdrs = getattr(exc, "response", None)
                if hdrs is not None:
                    retry_after = float(hdrs.headers.get("retry-after"))
            except Exception:
                retry_after = None
            delay = retry_after if retry_after else min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay += random.uniform(0, delay * 0.25)   # jitter to de-sync
            print(f"  [flex 429 no-capacity — free] attempt {attempt}/{max_attempts}; "
                  f"backing off {delay:.0f}s ({datetime.datetime.now():%H:%M:%S})", flush=True)
            time.sleep(delay)
    raise last


def main():
    args = parse_args()
    use_ci = not args.no_ci

    # Auto-name output folder from parameters if not specified
    if args.outdir is None:
        ci_tag      = "CI-on" if use_ci else "CI-off"
        calls_tag   = f"_max-calls-{args.max_tool_calls}" if args.max_tool_calls is not None else ""
        prompt_tag  = f"_{Path(args.prompt).stem.split(' - ')[0].replace(' ','')}" if args.prompt else ""
        folder_name = f"{args.model}_effort-{args.effort}_{ci_tag}{calls_tag}{prompt_tag}"
        outputs_dir = BASE / "outputs" / folder_name
    else:
        outputs_dir = BASE / "outputs" / args.outdir

    outputs_dir.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)

    # Load prompt — specific file or first found
    if args.prompt:
        query = args.prompt.lower()
        candidates = [f for f in PROMPT_DIR.glob("*.txt")
                      if query in f.stem.lower()]
        if not candidates:
            raise FileNotFoundError(f"No prompt file matching '{args.prompt}' in {PROMPT_DIR}")
        prompt_file = sorted(candidates)[0]
    else:
        prompt_files = sorted(PROMPT_DIR.glob("*.txt"))
        if not prompt_files:
            raise FileNotFoundError(f"No .txt prompt file found in {PROMPT_DIR}")
        prompt_file = prompt_files[0]
    prompt_text = prompt_file.read_text(encoding="utf-8")

    # Load image — specific file or first found
    if args.image:
        stem = Path(args.image).stem
        matches = [f for f in SCANS_DIR.iterdir()
                   if f.stem == stem and f.suffix.lower() in IMAGE_EXTENSIONS]
        if not matches:
            raise FileNotFoundError(f"Image '{args.image}' not found in {SCANS_DIR}")
        image_file = matches[0]
    else:
        image_files = [f for f in sorted(SCANS_DIR.iterdir()) if f.suffix.lower() in IMAGE_EXTENSIONS]
        if not image_files:
            raise FileNotFoundError(f"No image files found in {SCANS_DIR}")
        image_file = image_files[0]

    ci_label = "on" if use_ci else "off"
    tier_label = "flex" if args.flex else "default"
    print(f"Prompt  : {prompt_file.name}")
    print(f"Image   : {image_file.name}")
    calls_label = f"  |  max-tool-calls: {args.max_tool_calls}" if args.max_tool_calls is not None else ""
    print(f"Model   : {args.model}  |  effort: {args.effort}  |  CI: {ci_label}{calls_label}  |  tier: {tier_label}")
    print(f"Output  : {outputs_dir.relative_to(BASE)}")
    print("Sending request to OpenAI...\n")

    # Encode image
    image_bytes = image_file.read_bytes()
    image_b64   = base64.b64encode(image_bytes).decode("utf-8")
    media_type  = MIME.get(image_file.suffix.lower(), "image/jpeg")
    data_url    = f"data:{media_type};base64,{image_b64}"

    # Build tools list
    tools = [{"type": "code_interpreter", "container": {"type": "auto"}}] if use_ci else []

    create_kwargs = dict(
        model=args.model,
        reasoning={"effort": args.effort},
        tools=tools,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text",  "text": prompt_text},
                    {"type": "input_image", "image_url": data_url, "detail": "high"},
                ],
            }
        ],
    )
    if args.max_tool_calls is not None:
        create_kwargs["max_tool_calls"] = args.max_tool_calls

    if args.flex:
        create_kwargs["service_tier"] = "flex"
        response, n_attempts = _create_with_flex_backoff(create_kwargs, args.flex_max_attempts)
        if n_attempts > 1:
            print(f"(succeeded on attempt {n_attempts} after Flex no-capacity retries)\n")
    else:
        response = client.responses.create(**create_kwargs)

    output_text = response.output_text
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = image_file.stem

    (outputs_dir / f"{stem}_{ts}.txt").write_text(output_text, encoding="utf-8")

    log_payload = response.model_dump()
    log_path    = LOGS_DIR / f"{stem}_{ts}_{args.effort}_CI-{ci_label}_raw.json"
    log_path.write_text(json.dumps(log_payload, indent=2, default=str), encoding="utf-8")

    usage         = response.usage
    input_tokens  = usage.input_tokens
    output_tokens = usage.output_tokens
    reasoning_tokens = getattr(usage.output_tokens_details, "reasoning_tokens", 0)
    visible_tokens   = output_tokens - reasoning_tokens
    in_price, out_price = MODEL_PRICING.get(args.model, (5.00, 30.00))
    if args.flex:                      # Flex is billed at 50% off standard rates
        in_price  /= 2
        out_price /= 2
    input_cost    = (input_tokens  / 1_000_000) * in_price
    output_cost   = (output_tokens / 1_000_000) * out_price
    total_cost    = input_cost + output_cost

    # Confirm which tier OpenAI actually served (echoed back on the response).
    served_tier = getattr(response, "service_tier", None)

    print("--- Usage ---")
    print(f"Input tokens      : {input_tokens:,}")
    print(f"Output tokens     : {output_tokens:,}  (reasoning: {reasoning_tokens:,}  visible: {visible_tokens:,})")
    rate_note = "  (flex, 50% off)" if args.flex else ""
    print(f"Estimated cost    : ${total_cost:.4f}  (${input_cost:.4f} in + ${output_cost:.4f} out){rate_note}")
    print(f"Served tier       : {served_tier}")
    print()
    print(f"Output → {outputs_dir / f'{stem}_{ts}.txt'}")
    print(f"Log    → {log_path}")

    # Keep the batch+sync cost ledger current after every synchronous run too
    # (batch_transcribe.py auto-updates it for batch runs; this closes the sync gap).
    try:
        import batch_transcribe
        batch_transcribe._safe_update_ledger()
        print("Ledger → updated")
    except Exception as exc:
        print(f"Ledger → skipped ({exc})")

    return outputs_dir, stem, ts

if __name__ == "__main__":
    main()
