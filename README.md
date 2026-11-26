# Svežinka

The site is hosted on Cloudflare Workers. Customers, subscriptions, and orders are stored in Supabase.

Cloudflare Workers Builds should deploy with:

```sh
uv run pywrangler deploy
```

The Worker name in the Cloudflare dashboard must be `kosarica`, the same as `name` in `wrangler.jsonc`.

## Database

1. Create a free project at [supabase.com](https://supabase.com).
2. Open the SQL editor and run `supabase/schema.sql`.
3. Run `supabase/seed.sql`. This loads the sample customers and orders. Demo customer: `ana.horvat@example.com` / `kosarica`.
4. In Cloudflare, open the `kosarica` Worker, then Settings, then Variables and Secrets. Add:
   - `SUPABASE_URL` — Project URL from Supabase, like `https://xxxx.supabase.co`
   - `SUPABASE_SECRET_KEY` — the secret key from Supabase Project Settings, API (`sb_secret_...` or the legacy service_role key). `SUPABASE_SERVICE_ROLE_KEY` is also accepted. Do not use the publishable key.

Use the service role key only as a Worker secret. It can read and write every row. Do not put it in the repository or in a `NEXT_PUBLIC` variable.

Redeploy after the secrets are saved. New registrations, basket changes, and delivery statuses are then stored in Supabase and survive the next visit.

Without those two secrets, the Worker still opens and shows the baked-in sample data, but new orders disappear when Cloudflare restarts the Worker.
