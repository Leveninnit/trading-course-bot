# Trading Course Discord Bot

A single bot covering the four things a paid trading-education server usually needs:

- **Membership & access** — `/grant-access`, `/revoke-access`, `/extend-access`, `/membership`, plus an hourly background check that removes a member's role automatically when their access expires.
- **Moderation & safety** — auto-deletes banned words, scam/phishing domains, and (optionally) Discord invite links; basic anti-spam timeout; `/warn`, `/warnings`, `/clearwarnings`, `/kick`, `/ban`, `/timeout`, `/untimeout`; everything logs to a mod-log channel.
- **Engagement** — chat-based XP and levels (`/rank`, `/leaderboard`), a welcome message + rules-acceptance gate for onboarding, and button-based `/giveaway start|end`.
- **Support & content** — a ticket system (private channel per ticket, with a saved transcript on close), a simple FAQ auto-responder (`/faq add|remove|list`), and `/announce` for broadcasting lesson drops or market updates.

Nothing here is wired to a real payment processor yet, since that wasn't decided — `/grant-access` is the single function a future Stripe/Whop webhook would call, so that's a small add-on later rather than a rebuild.

## 1. Create the Discord application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) → **New Application** → name it (e.g. your course name).
2. Open the **Bot** tab → **Reset Token** → copy the token somewhere safe. You'll only see it once; if you lose it, reset it again.
3. On the same page, scroll to **Privileged Gateway Intents** and turn **ON**:
   - `SERVER MEMBERS INTENT` (needed for welcome messages and role checks)
   - `MESSAGE CONTENT INTENT` (needed for moderation, XP, and the FAQ responder)
4. Save changes.

If you ever plan to add this bot to 100+ servers Discord requires a verification/review process — not a concern for a single course server.

## 2. Invite the bot to your server

Open the **OAuth2 → URL Generator** tab.

- **Scopes:** check `bot` and `applications.commands`.
- **Bot permissions:** either:
  - Easiest: check **Administrator**, or
  - Least-privilege: `View Channels`, `Send Messages`, `Embed Links`, `Attach Files`, `Read Message History`, `Manage Messages`, `Manage Roles`, `Manage Channels`, `Kick Members`, `Ban Members`, `Moderate Members`.

Copy the generated URL, open it, pick your server, and authorize.

**Important:** In Server Settings → Roles, drag the bot's own role **above** every role it needs to manage (your tier roles, verified role, and above the members it should be able to timeout/kick/ban). Discord silently blocks role/moderation actions if the bot's role sits too low — this is the #1 cause of "the command ran but nothing happened."

## 3. Get the IDs you'll need

Turn on Developer Mode: User Settings → Advanced → Developer Mode. Then right-click any role, channel, or category → **Copy ID**.

## 4. Configure `config.json`

Everything except the bot token lives here (edit it directly, no code changes needed):

| Field | What it's for |
|---|---|
| `brand_name`, `brand_color` | Shown in every embed footer/color |
| `guild_id` | Your server's ID — makes slash commands appear instantly (recommended for a single-server bot). Leave `null` and commands still work everywhere, just take up to an hour to first appear. |
| `staff_role_ids`, `admin_role_ids` | Who can run staff commands (warn/kick/ban/tickets/announce) vs. admin-only commands (grant/revoke access) |
| `verified_role_id` | Role given when someone clicks "I Accept the Rules" |
| `welcome_channel_id` | Where join messages post |
| `mod_log_channel_id` | Where moderation actions, expirations, and ticket transcripts get logged |
| `level_up_channel_id` | Where level-up announcements post (defaults to the channel they spoke in if unset) |
| `ticket_category_id`, `ticket_support_role_ids` | Where ticket channels get created, and who can see them |
| `membership_tiers` | Map of tier key → `{ "role_id": ..., "label": ... }`. Add as many tiers as you want. |
| `xp_per_message`, `xp_cooldown_seconds` | Pace of leveling |
| `spam_message_threshold`, `spam_window_seconds`, `spam_timeout_seconds` | Anti-spam sensitivity |
| `warning_auto_timeout_threshold` | Auto 1-hour timeout after this many warnings (0/null to disable) |
| `allow_invites` | Set `true` to allow posting Discord invite links |
| `banned_words`, `scam_domains` | Auto-delete lists |
| `faq` | Default question-trigger → answer pairs (seeded into the database on first run; manage further with `/faq`) |

Every ID field can be left `null` — the bot just skips that feature until you fill it in, it won't crash.

## 5. Run it locally to test

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then paste your real token into .env
python bot.py
```

You should see `Logged in as YourBot#1234` in the console. Try `/post-rules-gate` and `/post-ticket-panel` in the relevant channels to post the persistent buttons.

## 6. Deploy it for free (Render)

Render's free web services need to pull your code from a Git repository (public repos work with no extra setup). The easiest no-CLI way:

1. Go to [github.com/new](https://github.com/new), create a **public** repo (e.g. `trading-course-bot`).
2. On the repo page, click **uploading an existing file**, drag in every file from this folder (keep the `cogs/` and `utils/` folders intact), and commit.
3. Copy the repo's URL (looks like `https://github.com/you/trading-course-bot`).

From there you have two options:

**Option A — tell me the repo URL and I'll finish it.** This workspace's Render account is already connected here — paste the repo URL back to me and I'll create the web service, wire up the free plan, and get it deploying. You'll still add your bot token yourself in Render's dashboard (Environment tab → Add Environment Variable → `DISCORD_TOKEN`) rather than pasting it in chat.

**Option B — do it yourself on Render's dashboard.** New → Web Service → connect the repo → Runtime: Python 3 → Build Command: `pip install -r requirements.txt` → Start Command: `python bot.py` → Plan: Free → add environment variable `DISCORD_TOKEN` → Create Web Service. The included `render.yaml` blueprint pre-fills all of this if you use Render's "Blueprint" deploy flow instead.

### Free-tier realities (read before you rely on this for paying members)

I looked this up rather than guessing, because it matters for a paid community:

- **It sleeps.** Render's free web services spin down after 15 minutes with no incoming HTTP request, and take about a minute to wake back up. A Discord bot's connection to Discord doesn't count as "incoming traffic," so left alone it will go offline repeatedly throughout the day.
  - **Fix:** the bot already runs a tiny `/health` web endpoint for this. Set up a free pinger — [cron-job.org](https://cron-job.org) (no card needed) → create a cron job hitting `https://<your-app-name>.onrender.com/health` every 10 minutes → this keeps it awake continuously.
- **Local storage resets.** Render's free filesystem is wiped on every redeploy or spin-down, and this bot's warnings/XP/membership data lives in a local SQLite file. With the keep-alive ping in place it should stay up (and keep its data) continuously between deploys, but any redeploy — or a Render-side restart — resets it.
  - **Upgrade paths, in order of effort:** (1) a paid Render instance (~$7/mo) with a persistent disk attached, so local storage survives everything; or (2) ask me and I'll swap the storage layer to a free Cloudflare D1 database instead (this session also has Cloudflare access) — that never expires and survives redeploys, at the cost of a little more setup.
  - **Not affected either way:** Discord itself is always the source of truth for roles/channels/messages — only the bot's *own* records (warning history, XP, who's tracked as "premium") are at risk.
- **750 free hours/month per workspace.** One bot running continuously uses ~744 hours, which just fits — but a second always-on free service in the same Render workspace will push you over and Render suspends every free service in the workspace until next month. Keep this as the only free service in the workspace, or upgrade it.

None of this is a reason not to use the free tier to get started — just don't be surprised if warning history resets after a big update, and consider the $7/mo tier or the D1 upgrade once real paying members depend on this.

## Command reference

**Membership** — `/grant-access`, `/revoke-access`, `/extend-access`, `/membership`
**Moderation** — `/warn`, `/warnings`, `/clearwarnings`, `/kick`, `/ban`, `/timeout`, `/untimeout` (auto-moderation runs passively on every message)
**Engagement** — `/rank`, `/leaderboard`, `/giveaway start`, `/giveaway end`
**Support & content** — `/post-ticket-panel`, `/announce`, `/faq add`, `/faq remove`, `/faq list`
**Onboarding** — `/post-rules-gate`

## Natural next steps (not built yet, on purpose)

- **Real payments:** a Stripe or Whop webhook that calls the same `grant_membership()` function `/grant-access` uses, so roles get assigned automatically on purchase instead of by a staff member running a command.
- **Level-based role rewards:** give a role automatically at certain XP levels (a few lines in `cogs/engagement.py`'s level-up check).
- **Smarter scam-link detection:** the current filter is an exact-match list in `config.json`; a lookalike-domain heuristic could catch more variants.

Ask me for any of these whenever you're ready — the codebase is already structured so they're additions, not rewrites.
