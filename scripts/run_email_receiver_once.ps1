Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
node .\scripts\email_receiver.mjs --once
