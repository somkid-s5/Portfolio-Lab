#!/usr/bin/env bash
# Install the checked-in, unmodified OFL font only on an ephemeral Linux CI runner.
set -euo pipefail
if [[ "${GITHUB_ACTIONS:-}" != "true" || "${RUNNER_OS:-}" != "Linux" ]]; then
  printf '%s\n' 'This helper is for GitHub Actions Linux runners only.' >&2
  exit 2
fi
for program in git install fc-cache fc-match timeout; do
  command -v "$program" >/dev/null
done
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="$repo_dir/tools/ci-fonts"
test "$(git hash-object "$source_dir/NotoSansThai.ttf")" = '34b48ab6f74867dbfce19410a2f452abef34e3ff'
test "$(git hash-object "$source_dir/OFL.txt")" = '7fa8dcb08ce4d2667b683ac4a8e79166e44e5277'
font_dir="$HOME/.local/share/fonts/portfolio-lab-ci"
mkdir -p -- "$font_dir"
install -m 0644 "$source_dir/NotoSansThai.ttf" "$font_dir/NotoSansThai.ttf"
install -m 0644 "$source_dir/OFL.txt" "$font_dir/OFL.txt"
timeout 30s fc-cache -f "$font_dir"
family="$(timeout 5s fc-match --format '%{family}\n' 'Noto Sans Thai')"
[[ "$family" == *"Noto Sans Thai"* ]]
printf '%s\n' 'CI_THAI_FONT=google/fonts@e7db6ca603fd4862010383ff17ffd6cc4ffac1c0 blob=34b48ab6f74867dbfce19410a2f452abef34e3ff'
