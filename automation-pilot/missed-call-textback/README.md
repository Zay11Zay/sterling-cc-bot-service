# Missed-Call Text-Back — Electrician Pilot

Free pilot automation: when a call to the business number isn't answered
within 20 seconds, the caller gets an auto-text so they don't hang up and
call the next electrician on Google. He also gets a text with who called.

No server to run — this deploys as two Twilio Functions (serverless,
free tier covers this easily).

## One-time setup (~20 minutes)

1. **Create a Twilio account**: https://www.twilio.com/try-twilio
   Free trial includes ~$15 credit, enough to fully build and test this.
   To text real customers (not just verified test numbers) you'll need to
   add a payment method and upgrade out of trial — cost at pilot volume is
   a few dollars a month, not more.

2. **Buy a phone number** matching his area code:
   Console → Phone Numbers → Buy a number → filter by area code → pick one
   with Voice + SMS capability (~$1.15/mo).

3. **Create a Functions service**:
   Console → Functions and Assets → Services → Create Service (name it
   e.g. `missed-call-pilot`).
   Add two functions inside it:
     - `/incoming-call` — paste in `functions/incoming-call.js`
     - `/call-status` — paste in `functions/call-status.js`

4. **Set environment variables** on that Functions service
   (Settings → Environment Variables):
   - `TWILIO_NUMBER` — the number you just bought, E.164 format (e.g. `+15551234567`)
   - `ELECTRICIAN_CELL` — his personal cell, E.164 format
   - `BUSINESS_NAME` — e.g. `Singletary Electric`

5. **Deploy** the service (button top-right). Copy the URL for
   `/incoming-call`.

6. **Wire the phone number to it**:
   Console → Phone Numbers → your number → Voice Configuration →
   "A call comes in" → Webhook → paste the `/incoming-call` URL → Save.

## Test it

Call the new Twilio number from a phone that isn't his cell. Let it ring
without answering on his end. Within ~20 seconds you should get an
auto-text on the calling phone, and he should get a text naming the caller.

## After the pilot proves out

- Point his Google Business Profile / website "call now" button at the new
  number so real traffic starts flowing through it.
- This is one of five automations in the fuller retainer package (review
  requests, quote follow-up, appointment reminders, lead intake → CRM) —
  natural upsell once he's seen this one work for a few weeks.
