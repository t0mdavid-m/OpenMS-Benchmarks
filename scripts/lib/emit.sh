#!/usr/bin/env bash
# Metric emission + measured-phase timing helpers. The MEASURED phase excludes
# on-demand provisioning, so wall_clock_s reflects the tool, not apt/pip.
METRICS_FILE="${OUT_DIR}/metrics.tsv"

metrics_init() { printf 'metric\tvalue\tunit\n' > "$METRICS_FILE"; }
metric_emit()  { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$METRICS_FILE"; }

# Reset cgroup-v2 peak after provisioning so peak_mem reflects the tool phase.
phase_start() {
  echo 0 > /sys/fs/cgroup/memory.peak 2>/dev/null || true
  PHASE_T0="$(date +%s.%N)"
}
phase_end() {
  local t1; t1="$(date +%s.%N)"
  local wall; wall="$(awk "BEGIN{printf \"%.3f\", ${t1} - ${PHASE_T0}}")"
  metric_emit wall_clock_s "$wall" s
  local peak; peak="$(cat /sys/fs/cgroup/memory.peak 2>/dev/null || true)"
  if [ -n "$peak" ]; then metric_emit peak_mem_bytes "$peak" bytes; fi
}
