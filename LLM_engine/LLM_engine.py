import ollama
import sys
import os
import json

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
                "Nuttiess Chocolate",
                "NIVEA",
                "Shampoo",
                "Appy Fizz",
                "Cough Syrup",
                "Coca Cola",
                "Tea Botx",
                "Pringles",
                "Noodles",
                "Bar",
                "Ponds",
                "Dove",
            ],
            "properties": {
                "Nuttiess Chocolate": {"type": "integer"},
                "NIVEA": {"type": "integer"},
                "Shampoo": {"type": "integer"},
                "Appy Fizz": {"type": "integer"},
                "Cough Syrup": {"type": "integer"},
                "Coca Cola": {"type": "integer"},
                "Tea Botx": {"type": "integer"},
                "Pringles": {"type": "integer"},
                "Noodles": {"type": "integer"},
                "Bar": {"type": "integer"},
                "Ponds": {"type": "integer"},
                "Dove": {"type": "integer"},
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
                payload = json.loads(answer)
            except json.JSONDecodeError:
                correction = client.chat(
                    model=selected_model,
                    messages=build_messages(
                        history,
                        f"Return ONLY valid JSON that matches the required schema. Fix this output: {answer}",
                    ),
                    format=STRICT_JSON_SCHEMA,
                )
                answer = correction['message']['content']
                payload = json.loads(answer)

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
