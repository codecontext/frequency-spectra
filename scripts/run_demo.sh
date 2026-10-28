#!/usr/bin/env bash
set -euo pipefail

usage() {
	cat <<'EOF'
Usage: scripts/run_demo.sh [--live | --finite]

Build and run continuous plotting by default. Use --finite for the one-shot DSP test.

Environment overrides:
  ZEPHYR_WORKSPACE  Zephyr workspace root (default: ../zephyrproject)
  HOST_PYTHON       Host Python with Matplotlib installed (live mode only)
EOF
}

mode="live"
case "${1:-}" in
	"") ;;
	--live) mode="live" ;;
	--finite) mode="finite" ;;
	-h|--help)
		usage
		exit 0
		;;
	*)
		usage >&2
		exit 2
		;;
esac

if [[ $# -gt 1 ]]; then
	usage >&2
	exit 2
fi

app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
workspace="${ZEPHYR_WORKSPACE:-"$app_dir/../zephyrproject"}"
workspace="$(cd -- "$workspace" 2>/dev/null && pwd)" || {
	printf 'Zephyr workspace not found. Set ZEPHYR_WORKSPACE to its root.\n' >&2
	exit 1
}

if [[ ! -f "$workspace/.west/config" ]]; then
	printf 'No west workspace found at %s. Set ZEPHYR_WORKSPACE to its root.\n' "$workspace" >&2
	exit 1
fi

if command -v west >/dev/null 2>&1; then
	west_cmd="$(command -v west)"
elif [[ -x "$workspace/.venv/bin/west" ]]; then
	west_cmd="$workspace/.venv/bin/west"
else
	printf 'west was not found on PATH or in %s/.venv/bin.\n' "$workspace" >&2
	exit 1
fi

if [[ "$mode" == "live" ]]; then
	host_python="${HOST_PYTHON:-$(command -v python3 || true)}"
	if [[ -z "$host_python" ]]; then
		printf 'Host Python 3 was not found. Set HOST_PYTHON explicitly.\n' >&2
		exit 1
	fi
	if [[ "$host_python" == "$workspace/.venv/"* ]]; then
		if [[ -x /usr/bin/python3 ]]; then
			host_python=/usr/bin/python3
		else
			printf 'The selected Python is the Zephyr environment. Set HOST_PYTHON to a host interpreter with Matplotlib.\n' >&2
			exit 1
		fi
	fi
	if [[ ! -x "$host_python" ]]; then
		printf 'Host Python is not executable: %s\n' "$host_python" >&2
		exit 1
	fi
	if ! "$host_python" -c 'import matplotlib, numpy' >/dev/null 2>&1; then
		printf 'Host Python must have Matplotlib and NumPy installed: %s\n' "$host_python" >&2
		exit 1
	fi

	build_dir="$app_dir/build/live"
	(
		cd -- "$workspace"
		"$west_cmd" build --pristine=always -b qemu_cortex_a53 \
			-d "$build_dir" "$app_dir" -- -DFREQSPEC_LIVE=ON
	)

	printf 'Starting live QEMU plot. Stop QEMU with Ctrl+A, then X.\n'
	set -o pipefail
	(
		cd -- "$workspace"
		"$west_cmd" build -d "$build_dir" -t run
	) 2>&1 \
		| "$host_python" "$app_dir/scripts/plot_capture.py" --live
else
	build_dir="$app_dir/build/finite"
	(
		cd -- "$workspace"
		"$west_cmd" build --pristine=always -b qemu_cortex_a53 \
			-d "$build_dir" "$app_dir"
		"$west_cmd" build -d "$build_dir" -t run
	)
fi