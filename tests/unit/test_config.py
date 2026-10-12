from app.config import Settings


def test_dsn_encodes_special_characters_in_password():
    settings = Settings(
        _env_file=None,                 # ignore the real .env; this test controls every value
        postgres_user="fraudstream",
        postgres_password="pa@ss:word/1",
        postgres_db="fraudstream",
    )
    assert "pa%40ss%3Aword%2F1" in settings.postgres_dsn   
    assert "@localhost:" in settings.postgres_dsn