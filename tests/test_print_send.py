import json
from types import SimpleNamespace

from server.printpipeline import send


import pytest


@pytest.mark.parametrize('device_reply', [{'result':'success'}, {'err_code':84033543}])
def test_command_waits_for_matching_printer_ack(monkeypatch,device_reply):
    import paho.mqtt.client as mqtt
    sent = []

    class Client:
        def __init__(self, *args, **kwargs): pass
        def tls_set_context(self, *args): pass
        def username_pw_set(self, *args): pass
        def connect(self, *args, **kwargs): pass
        def subscribe(self, *args, **kwargs): pass
        def disconnect(self): pass
        def loop_stop(self): pass
        def publish(self, topic, payload, **kwargs):
            sent.append(json.loads(payload)['print'])
        def loop_start(self):
            self.on_connect(self, None, None, 0)
            self.on_subscribe(self, None, 1, [0])
            self.on_message(self, None, SimpleNamespace(payload=json.dumps({'print': {
                'sequence_id':sent[0]['sequence_id'], **device_reply}})))

    monkeypatch.setattr(mqtt, 'Client', Client)
    result = send.mqtt_send_print('serial','ip','secret','test','hash',remote_name='test.gcode.3mf')
    if 'result' in device_reply:
        assert result['accepted'] is True
        assert result['started'] is False
    else:
        assert result['ok'] is False
        assert result['errorCode']==84033543
    assert sent[0]['url'] == 'ftp:///test.gcode.3mf'
    assert sent[0]['param'] == 'Metadata/plate_1.gcode'


def test_invalid_remote_path_is_rejected_before_connect():
    assert not send.mqtt_send_print('s','i','p','n','h',remote_name='../other.3mf')['ok']
