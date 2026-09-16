$ErrorActionPreference = "Stop"

$session = "little-tutor-browser"
$baseUrl = $env:TUTOR_BASE_URL
if (-not $baseUrl) {
    $baseUrl = "http://127.0.0.1:8010"
}

npx --yes --package @playwright/cli playwright-cli `
    "-s=$session" close
npx --yes --package @playwright/cli playwright-cli `
    "-s=$session" open $baseUrl
npx --yes --package @playwright/cli playwright-cli `
    "-s=$session" run-code --filename scripts/browser_acceptance.js
