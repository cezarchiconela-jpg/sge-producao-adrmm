# Arranque local do SGE no Windows PowerShell
Set-Location $PSScriptRoot
if (!(Test-Path ".venv")) {
    python -m venv .venv
}
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$env:FLASK_DEBUG="1"
$env:SGE_REQUIRE_LOGIN="0"
python app.py
