import os

from ariane_env import load_dotenv


def test_load_dotenv_reads_repo_style_file_without_overriding_existing_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        """
        # comments and blank lines are ignored
        ARIANE_RECORD="data/2026-07-02-matin"
        export WHISPER_STREAMING_PATH=C:/ws/path # inline comment
        NOTIFY_SEND=
        EXISTING=from_file
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("EXISTING", "from_process")

    loaded = load_dotenv(env)

    assert loaded["ARIANE_RECORD"] == "data/2026-07-02-matin"
    assert loaded["WHISPER_STREAMING_PATH"] == "C:/ws/path"
    assert loaded["NOTIFY_SEND"] == ""
    assert os.environ["EXISTING"] == "from_process"
    assert "EXISTING" not in loaded
