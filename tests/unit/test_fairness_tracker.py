def test_fairness_tracker_initial_state():
    from lib.concurrency import FairnessTracker
    ft = FairnessTracker(resume_threshold=10)
    assert not ft.should_force_log_incident()


def test_fairness_after_10_resumes_force_logincident():
    from lib.concurrency import FairnessTracker, ResumeWork, LogIncident
    ft = FairnessTracker(resume_threshold=10)
    for _ in range(10):
        ft.note_drained(ResumeWork(session_id="s", user_reply=True))
    assert ft.should_force_log_incident()


def test_fairness_resets_after_logincident_drained():
    from lib.concurrency import FairnessTracker, ResumeWork, LogIncident
    ft = FairnessTracker(resume_threshold=10)
    for _ in range(10):
        ft.note_drained(ResumeWork(session_id="s", user_reply=True))
    assert ft.should_force_log_incident()
    # Implementer drains 1 LogIncident
    ft.note_drained(LogIncident(cluster_id="c", first_seen=None, last_seen=None,
                                occurrences=1, raw_lines=[], severity_hint="ERROR",
                                likely_addon=None, likely_action=None,
                                backdated=False, from_previous_session=False,
                                triage_deferred=True))
    assert not ft.should_force_log_incident()


def test_fairness_user_msg_does_not_count_as_resume():
    from lib.concurrency import FairnessTracker, UserMsg
    ft = FairnessTracker(resume_threshold=10)
    for _ in range(20):
        ft.note_drained(UserMsg(chat_id=1, text="x", message_id=1, reply_to_message_id=None))
    assert not ft.should_force_log_incident()


def test_peek_logincident_returns_priority_position():
    """Helper for T4 to check if a LogIncident is queued before forcing."""
    from lib.concurrency import work_queue, enqueue, LogIncident, ResumeWork
    from lib.concurrency import has_pending_logincident
    while not work_queue.empty():
        work_queue.get_nowait()
    enqueue(ResumeWork(session_id="s", user_reply=True))
    assert not has_pending_logincident()
    enqueue(LogIncident(cluster_id="c", first_seen=None, last_seen=None,
                        occurrences=1, raw_lines=[], severity_hint="ERROR",
                        likely_addon=None, likely_action=None, backdated=False,
                        from_previous_session=False, triage_deferred=True))
    assert has_pending_logincident()
