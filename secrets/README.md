# Secrets

Production secrets are stored as sops-encrypted YAML files in this directory,
decrypted at container startup via `scripts/entrypoint.sh`.

## First-time setup

1. Generate an age keypair on your laptop:
   ```
   age-keygen -o ~/.donna/age.key
   cat ~/.donna/age.key | grep '# public key:'
   ```

2. `.sops.yaml` at repo root is where sops looks up which age recipient(s)
   to encrypt to. It's scaffolded — list **two** comma-separated public keys
   (primary + a paper-backup stored offline) so losing either one still
   leaves the secrets recoverable. See `docs/OPERATIONS.md` §DR.
   ```yaml
   creation_rules:
     - path_regex: secrets/.*\.enc\.yaml$
       age: age1primary...,age1backup...
   ```

3. Create `secrets/prod.enc.yaml` (encrypted). Format is **YAML** (`KEY: value`),
   not dotenv — `scripts/entrypoint.sh` parses with `yaml.safe_load` and
   aborts container startup if the decrypted content isn't a top-level
   mapping. Quote snowflake IDs so YAML keeps them as strings. Use
   `--filename-override` so sops applies the `.sops.yaml` rule whose
   `path_regex` matches the destination path:
   ```bash
   cat > /tmp/plain.yaml <<'EOF'
   DISCORD_BOT_TOKEN: ...
   DISCORD_ALLOWED_USER_ID: "123456789012345678"
   DISCORD_GUILD_ID: "123456789012345678"   # optional
   ANTHROPIC_API_KEY: sk-ant-...
   TAVILY_API_KEY: tvly-...
   VOYAGE_API_KEY: pa-...
   EOF
   sops --filename-override secrets/prod.enc.yaml -e /tmp/plain.yaml > secrets/prod.enc.yaml
   rm /tmp/plain.yaml
   ```

4. Copy the private key to the droplet (one-time):
   ```
   scp ~/.donna/age.key scout:/etc/bot/age.key
   ssh scout "sudo chmod 600 /etc/bot/age.key && sudo chown bot:bot /etc/bot/age.key"
   ```

## Rotation

Every 90 days:
 - Rotate each API key with its provider
 - Re-encrypt `prod.enc.yaml` with sops
 - Commit the new encrypted file, push, droplet picks up within 5 min
 - Leave the age key alone; only rotate age on a machine change

## What is NEVER committed

 - `age.key` (the private key)
 - Plain `.env.production` / `.env`
 - Anything not encrypted by sops

See `.gitignore`.
