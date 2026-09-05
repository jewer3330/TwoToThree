from server.printer.bambu import parse_print


def test_running_state_is_not_replaced_by_stage_number():
    status = parse_print({'print': {'gcode_state': 'RUNNING', 'stg_curr': 4,
                                    'mc_remaining_time': 12}})
    assert status['state'] == 'running'
    assert status['remainingSeconds'] == 720


def test_partial_report_does_not_claim_idle():
    assert parse_print({'print': {'bed_temper': 29}})['state'] == 'unknown'
