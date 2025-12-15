from flask import Flask, request, jsonify
import requests
import threading

app = Flask(__name__)

# vLLM replicas
VLLM_PORTS = list(range(8001, 8009))
VLLM_URLS = [f"http://localhost:{port}" for port in VLLM_PORTS]

# Round-robin counter and lock
lock = threading.Lock()
counter = 0

@app.route("/v1/<path:endpoint>", methods=["POST", "GET", "OPTIONS"])
def proxy_vllm(endpoint):
    global counter
    with lock:
        target = VLLM_URLS[counter % len(VLLM_URLS)]
        counter += 1

    url = f"{target}/v1/{endpoint}"

    try:
        # Forward the request with original method and headers
        headers = dict(request.headers)
        method = request.method

        if method == "POST":
            response = requests.post(url, headers=headers, json=request.get_json())
        elif method == "GET":
            response = requests.get(url, headers=headers, params=request.args)
        elif method == "OPTIONS":
            response = requests.options(url, headers=headers)
        else:
            return jsonify({"error": f"Method {method} not supported"}), 405

        return (response.content, response.status_code, response.headers.items())

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to connect to backend {url}", "details": str(e)}), 502

@app.route("/")
def health():
    return "vLLM load balancer is running."

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)
