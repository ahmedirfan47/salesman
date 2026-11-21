# Incident response plan

Owner: Ahmed Irfan (ahmed@stonic.site). Reviewed every 6 months and after every incident.

## Severity

| Level | Examples | First response |
| --- | --- | --- |
| **Critical** | Personal data exposed to someone who shouldn't see it; another business's data visible; leaked keys | Immediately, any hour |
| **High** | Order-taking down for a customer; WhatsApp or ERP sync failing for everyone | Within 2 hours, any hour |
| **Normal** | One feature broken, one customer's sync failing | Next business day |

## Steps

1. **Contain** (first hour). Stop the damage: revoke exposed keys and sessions (sign out everywhere, rotate
   `JWT_SECRET`, WhatsApp tokens, ERP keys, print-agent keys), pause the affected ERP connection or feature,
   take the service offline if data is still leaking.
2. **Assess** (first 12 hours). Which businesses, which people, which data, since when. Use the audit logs,
   ERP sync log, sign-in log and hosting logs. Write it down as you go: time, what you found, what you did.
3. **Notify** (within 24 hours of becoming aware, for anything touching personal data). Tell each affected
   customer in writing: what happened, which data and people, likely consequences, what was done and what they
   should do. This gives them time to notify SDAIA within 72 hours and to inform affected people where the law
   requires.
4. **Fix and recover.** Deploy the fix, restore from backup if data was lost, confirm with a test, re-enable
   what was paused.
5. **Review** (within 5 business days). What happened, why, what changes so it can't happen again. Share the
   summary with affected customers.

## Contacts

| Who | How |
| --- | --- |
| Stonic incident lead | Ahmed Irfan — ahmed@stonic.site |
| Hosting (API, database) | Render support (dashboard) |
| Dashboard hosting | Vercel support (dashboard) |
| WhatsApp | Meta Business support |
| Saudi data regulator | SDAIA, National Data Management Office (via the customer, as controller) |

## Breach notice template (to the customer)

> Subject: Security incident affecting your Salesman account — [date]
>
> On [date/time] we found [what happened]. It affected [which data] of [how many / which] people between
> [start] and [end]. We have [containment steps]. You may need to notify SDAIA within 72 hours of this notice
> and inform the people affected; we will give you any information you need for that. What you can do now:
> [steps]. We will update you by [time]. — Ahmed Irfan, Founder & CEO, Stonic
