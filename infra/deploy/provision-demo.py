"""Retired: password-based demo identities cannot use the Google-only application."""

if __name__ == "__main__":
    raise SystemExit(
        "Dummy user provisioning has been removed. Configure ADMIN_EMAIL in deploy.env "
        "and sign in with Google. For local image fixtures use ./infra/seed-demo.sh."
    )
