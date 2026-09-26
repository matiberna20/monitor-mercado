from monitor_mercado.configuracion import Secretos


def test_variables_vacias_cuentan_como_no_configuradas(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=123:abc\nTELEGRAM_CHAT_ID=\n", encoding="utf-8")
    s = Secretos(_env_file=env)
    assert s.telegram_chat_id is None
    assert not s.telegram_configurado
