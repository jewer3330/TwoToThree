"""网络可恢复失败分类与调度重试记簿单测。"""
from server.gpu.selfreg_remote import is_network_error


def test_is_network_error_classifies_transport_failures():
    assert is_network_error('节点离线或消息投递失败')
    assert is_network_error('命令执行超时（4500s），节点可能卡死')
    assert is_network_error('回传超时（600s）')
    assert is_network_error('connection reset by peer')
    assert not is_network_error('节点命令退出码 1')
    assert not is_network_error('ModuleNotFoundError: No module named hy3dgen')
    assert not is_network_error(None)
    assert not is_network_error('')


def test_host_failure_penalty_and_retry_backoff(monkeypatch):
    from server.gpu import hosts
    hid='gpu_test_1'
    monkeypatch.setattr(hosts, '_FAIL_PENALTY_WINDOW', 600)
    hosts._state.pop(hid, None)
    assert hosts.host_failure_streak(hid) == 0
    hosts.record_host_failure(hid)
    hosts.record_host_failure(hid)
    assert hosts.host_failure_streak(hid) == 2
    hosts.record_host_success(hid)
    assert hosts.host_failure_streak(hid) == 0

    jid='job_retrytest'
    hosts._net_retry.pop(jid, None)
    assert hosts.network_retry_ready(jid) is True
    hosts.schedule_network_retry(jid, 30)
    assert hosts.network_retry_ready(jid) is False
    assert hosts.network_retry_delay(jid) > 0
    monkeypatch.setattr(hosts, '_net_retry', {jid: 0})  # 已到期
    assert hosts.network_retry_ready(jid) is True
