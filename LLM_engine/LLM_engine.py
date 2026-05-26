import ollama
import sys
import os
import json
import re

MODEL = os.environ.get('OLLAMA_MODEL', 'llama3')  # Change or set OLLAMA_MODEL env var
PRECONTEXT_FILE = os.path.join(os.path.dirname(__file__), 'precontext.txt')
STRICT_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["response", "cart"],
    "properties": {
        "response": {"type": "string"},
        "cart": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "Coke Zero",
                "Diet Coke",
                "Cough Medicine",
                "Crepe Bandage",
                "Ball_Red",
                "Ball_Yellow",
                "Ball_Blue",
                "Capsule Bottle",
                "Tea",
                "Bearing",
            ],
            "properties": {
                "Coke Zero": {"type": "integer"},
                "Diet Coke": {"type": "integer"},
                "Cough Medicine": {"type": "integer"},
                "Crepe Bandage": {"type": "integer"},
                "Ball_Red": {"type": "integer"},
                "Ball_Yellow": {"type": "integer"},
                "Ball_Blue": {"type": "integer"},
                "Capsule Bottle": {"type": "integer"},
                "Tea": {"type": "integer"},
                "Bearing": {"type": "integer"},
            },
        },
    },
}


def load_precontext():
    if os.path.exists(PRECONTEXT_FILE):
        with open(PRECONTEXT_FILE, 'r') as f:
            return f.read().strip()
    return ''


def build_messages(history, user_input):
    messages = list(history)
    messages.append({"role": "user", "content": user_input})
    return messages


def is_valid_payload(payload):
    if not isinstance(payload, dict):
        return False
    if set(payload.keys()) != {"response", "cart"}:
        return False
    if not isinstance(payload.get("response"), str):
        return False
    cart = payload.get("cart")
    if not isinstance(cart, dict):
        return False
    required_keys = STRICT_JSON_SCHEMA["properties"]["cart"]["required"]
    if set(cart.keys()) != set(required_keys):
        return False
    return all(isinstance(cart[key], int) for key in required_keys)


def extract_json_candidates(text):
    """Yield JSON values embedded in raw model text."""
    if not isinstance(text, str):
        return
    stripped = text.strip()
    if not stripped:
        return

    fence_match = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    if fence_match:
        yield from extract_json_candidates(fence_match.group(1))

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        yield value


def normalize_payload(payload):
    required_keys = STRICT_JSON_SCHEMA["properties"]["cart"]["required"]
    cart = payload.get("cart", {})
    normalized_cart = {}
    for key in required_keys:
        try:
            normalized_cart[key] = int(cart.get(key, 0))
        except (TypeError, ValueError):
            normalized_cart[key] = 0
    return {
        "response": str(payload.get("response", "")).strip(),
        "cart": normalized_cart,
    }


def parse_llm_payload(answer):
    pending = [answer]
    seen = set()
    while pending:
        value = pending.pop(0)
        marker = repr(value)[:1000]
        if marker in seen:
            continue
        seen.add(marker)

        if isinstance(value, dict):
            if "response" in value or "cart" in value:
                payload = normalize_payload(value)
                if is_valid_payload(payload):
                    return payload
            for key in ("content", "message", "data", "output"):
                if key in value:
                    pending.append(value[key])
        elif isinstance(value, list):
            pending.extend(value)
        elif isinstance(value, str):
            for candidate in extract_json_candidates(value):
                pending.append(candidate)

    raise ValueError("Model output did not contain a valid response/cart JSON payload")

def main():
    client = ollama.Client()
    # Resolve a usable model from the Ollama instance
    try:
        available = [m.model for m in client.list().models]
    except Exception:
        available = []
    if MODEL in available:
        selected_model = MODEL
    else:
        # prefer a model that contains the requested name, otherwise pick first available
        candidates = [m for m in available if MODEL in m]
        selected_model = candidates[0] if candidates else (available[0] if available else MODEL)
    if selected_model != MODEL:
        print(f"[Engine] requested model '{MODEL}' not found, using '{selected_model}' instead", file=sys.stderr)
    history = []
    precontext = load_precontext()
    if precontext:
        history.append({"role": "system", "content": precontext})
    while True:
        try:
            user_input = sys.stdin.readline()
            if not user_input:
                break
            user_input = user_input.strip()
            if user_input.lower() in {"exit", "quit"}:
                break
            if not user_input:
                continue

            response = client.chat(
                model=selected_model,
                messages=build_messages(history, user_input),
                format=STRICT_JSON_SCHEMA,
                options={
                    "temperature": 0.1,
                    "top_p": 0.2,
                    "repeat_penalty": 1.1,
                },
            )
            answer = response['message']['content']
            try:
                payload = parse_llm_payload(answer)
            except Exception:
                correction = client.chat(
                    model=selected_model,
                    messages=build_messages(
                        history,
                        f"Return ONLY valid JSON that matches the required schema. Fix this output: {answer}",
                    ),
                    format=STRICT_JSON_SCHEMA,
                )
                answer = correction['message']['content']
                payload = parse_llm_payload(answer)

            if not is_valid_payload(payload):
                raise ValueError("Model returned JSON that does not match the required schema")

            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": json.dumps(payload)})
            print(json.dumps({"role": "assistant", "content": json.dumps(payload)}))
            sys.stdout.flush()
        except Exception as e:
            print(json.dumps({"error": str(e)}))
            sys.stdout.flush()
            break

if __name__ == "__main__":
    main()
