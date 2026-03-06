from webu.google_api.profile_bootstrap import create_encrypted_profile_archive
from webu.google_api.scraper import GoogleScraper


def test_google_scraper_bootstraps_from_encrypted_archive(tmp_path, monkeypatch):
    source_dir = tmp_path / "source_profile"
    source_dir.mkdir()
    (source_dir / "google_cookies.json").write_text("[]\n", encoding="utf-8")
    (source_dir / "Local State").write_text("{}\n", encoding="utf-8")
    (source_dir / "WidevineCdm").mkdir()
    (source_dir / "WidevineCdm" / "blob.bin").write_text("secret\n", encoding="utf-8")
    (source_dir / "Default").mkdir()
    (source_dir / "Default" / "Preferences").write_text("{}\n", encoding="utf-8")
    (source_dir / "Default" / "Cookies").write_text("cookies\n", encoding="utf-8")
    (source_dir / "Default" / "History").write_text("history\n", encoding="utf-8")

    archive_path = tmp_path / "google_api_profile.bin"
    create_encrypted_profile_archive(source_dir, archive_path, "bootstrap-secret")

    restored_dir = tmp_path / "restored_profile"
    monkeypatch.setenv("WEBU_GOOGLE_PROFILE_BOOTSTRAP_ARCHIVE", str(archive_path))
    monkeypatch.setenv("WEBU_GOOGLE_API_TOKEN", "bootstrap-secret")

    scraper = GoogleScraper(headless=True, verbose=False, profile_dir=restored_dir)
    scraper._bootstrap_profile_dir()

    assert (restored_dir / "google_cookies.json").exists()
    assert (restored_dir / "Local State").exists()
    assert (restored_dir / "Default" / "Preferences").exists()
    assert (restored_dir / "Default" / "Cookies").exists()
    assert not (restored_dir / "WidevineCdm").exists()
    assert not (restored_dir / "Default" / "History").exists()