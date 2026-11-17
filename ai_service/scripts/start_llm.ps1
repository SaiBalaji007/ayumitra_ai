# Starts the local Qwen2.5-3B-Instruct inference server (llama.cpp, CPU, 4-bit Q4_K_M GGUF).
# Exposes an OpenAI-compatible API on http://127.0.0.1:8081/v1, used by ayumitra_ai.llm.client.
#
# One-time setup (already done by the setup steps in ai_service/README.md):
#   runtime\llama\       official llama.cpp Windows CPU build (github.com/ggml-org/llama.cpp releases)
#   models\qwen2.5-3b-instruct-q4_k_m.gguf   from huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF
#
# Usage (from ai_service\):  powershell -ExecutionPolicy Bypass -File scripts\start_llm.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$server = Join-Path $root "runtime\llama\llama-server.exe"
$model = Join-Path $root "models\qwen2.5-3b-instruct-q4_k_m.gguf"

if (-not (Test-Path $server)) { throw "llama-server.exe not found at $server" }
if (-not (Test-Path $model)) { throw "Model not found at $model" }

# Use physical cores minus two so the laptop stays responsive.
$threads = [Math]::Max(2, (Get-CimInstance Win32_Processor).NumberOfCores - 2)

& $server -m $model --host 127.0.0.1 --port 8081 -c 8192 -t $threads --alias qwen2.5-3b-instruct --jinja
