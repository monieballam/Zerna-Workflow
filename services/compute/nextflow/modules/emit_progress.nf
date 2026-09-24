/*
 * EMIT_PROGRESS process — sends progress events to the Control Plane API.
 * Lightweight HTTP POST; runs on local executor regardless of profile.
 * Requirements: 4.17
 */

process EMIT_PROGRESS {
    executor 'local'
    tag      "${run_id}:${step}"

    input:
        val run_id
        val step
        val step_status
        val control_plane_url
        val control_plane_token

    output:
        stdout

    script:
    def auth_header = control_plane_token ? "-H 'Authorization: Bearer ${control_plane_token}'" : ""
    """
    curl -s -X POST "${control_plane_url}/v1/runs/${run_id}/progress" \
        -H 'Content-Type: application/json' \
        ${auth_header} \
        -d '{"step": "${step}", "status": "${step_status}"}' \
        || echo "Warning: progress event delivery failed for step ${step}"
    """

    stub:
    """
    echo "STUB: progress event ${step}=${step_status} for run ${run_id}"
    """
}
