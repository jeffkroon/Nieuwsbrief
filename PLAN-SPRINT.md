# Plan: nieuwsbrief-tool volwassen maken (sprint van 3 uur, 18 september 2026)

> **Status 18 september, einde sprint:** blok 0 t/m 5 gebouwd, in vier PR's die op
> elkaar stapelen (#72 -> #73 -> #74 -> #75). Ongepland toegevoegd: verificatie van
> de drie ESP-API's tegen hun documentatie, met twee echte fouten opgelost
> (ESP-API-VERIFICATIE.md). 493 tests groen tegen een echte Postgres.
> Niet gebouwd: de testmail-knop (blok 3), zie de toelichting in PR #74.

Doel: alles wat nu clunky of half is werkend en soepel maken, in zes blokken van
elk een eigen PR. Volgorde is op impact voor de accountmanager. Wat onder de
streep staat schuift door als we achterlopen.

Uitgangspunten (blijven staan):
- Garanties in code, niet in de prompt (200-check, live prijs, toestemming-gate,
  byte-gelijke tool-proof round-trip, alleen concepten, nooit verzenden).
- Elke PR: tests groen, code-review, squash-merge, deploy via push op main.

---

## Blok 0: startklaar (10 min)

- [x] PR #71 gemerged (diagnostiek weg). Permissie voor `gh pr merge` toevoegen in
      `.claude/settings.local.json` zodat merges niet meer blokkeren.
- [x] Branch per blok: `feat/templates-volwassen`, `feat/chat-streaming`,
      `feat/nieuwsbrieven-tab`, `feat/kwaliteitslaag`, `chore/model-sonnet-5`.
- [x] Tekstschuld: tool-beschrijving `create_newsletter_draft` ("Brevo, Klaviyo
      of ActiveCampaign"), textarea-hint in Templates-tab bijwerken naar kaarten,
      `##SECTIES##` en `{{VAK_*}}`.

## Blok 1: templates volwassen (45 min)

Nu: plakken in een textarea, opgeslagen template alleen te verwijderen, geen
versies, rapport is een tekstblok.

- [x] **Upload**: `.html` of `.zip` via `POST /tenants/{id}/templates/upload`
      (multipart). ZIP: afbeeldingen naar Supabase Storage onder
      `{tenant}/templates/{uuid}/`, `src`-verwijzingen herschrijven naar de
      publieke URL. Drag-and-drop-zone naast de textarea; textarea blijft voor
      plakken.
- [x] **Bewerken**: knop "Bewerken" per opgeslagen template laadt naam, HTML en
      stijl in het formulier; opslaan gaat via de bestaande `PUT`.
- [x] **Versies**: migratie `mail_012_template_versions.sql` (template_id, html,
      styles, bron: upload/toolproof/handmatig/terugzetten, actor, created_at).
      Elke create/update schrijft een versie. `GET .../versions` en
      `POST .../versions/{n}/restore`. UI: uitklaplijst met datum + bron +
      "Terugzetten".
- [x] **Diff-weergave tool-proof**: origineel links, resultaat rechts, met
      `diff2html` (cdnjs) op basis van een server-side unified diff
      (`difflib.unified_diff`). Vervangt het pre-wrap-blok, `applied`/`failed`
      blijven als lijst eronder.
- [x] **Capabilities-kaartje**: na tool-proof en bij selectie van een template
      toont de UI wat de template kan (`template_capabilities()` bestaat al):
      header-foto, intro's, kaarten, secties, invulvakken, knoppen, witruimtes.
- [x] **Preview met echte inhoud**: `POST /templates/preview` accepteert
      optioneel `newsletter_id`; dan wordt de `input` van die nieuwsbrief als
      voorbeelddata gebruikt in plaats van `_SAMPLE`.

Tests: upload (html en zip, verkeerde bestanden geweigerd), versies (schrijven,
terugzetten, tenant-scoping), diff-endpoint, preview met newsletter_id.

## Blok 2: chat als werkomgeving (45 min)

Nu: één blokkerende POST tot 90 s, F5 wist het gesprek, geen geschiedenis.

- [x] **Streaming met tussenstappen**: `POST /conversations/{id}/messages/stream`
      via `sse-starlette`. De orchestrator krijgt een `on_event`-callback en
      stuurt per tool-call een leesbare regel ("15 wedstrijden gevonden op
      /tickets/serie-a", "prijzen gecheckt: 15/15 bereikbaar", "voorbeeld
      gerenderd"). Slot-event bevat het antwoord + preview. Oude endpoint blijft
      voor tests en API-gebruik.
- [x] **Annuleren**: knop "Stop" die de fetch afbreekt; server stopt de loop bij
      client-disconnect (check `request.is_disconnected()` tussen iteraties).
- [x] **Gesprekken bewaren**: `GET /conversations?tenant_id=` (laatste 30, met
      eerste bericht als titel, datum, of er een concept uit kwam) en
      `GET /conversations/{id}` (berichten + last_preview). Zijbalk links in de
      Chat-tab, `conversationId` in `localStorage` per tenant, hervatten na F5.
- [x] **Snelstarts**: drie knoppen boven het invoerveld, gevuld uit
      `content_types` van de tenant ("Weekend-wedstrijden", "Nieuwe reizen",
      "Productupdate").

Tests: SSE-event-volgorde met fake LLM, disconnect stopt de loop, lijst is
tenant-gescoped (klant ziet alleen eigen gesprekken).

## Blok 3: nieuwsbrieven-tab (30 min)

Nu: `Newsletter`-tabel wordt gevuld maar is nergens zichtbaar.

- [x] Router `GET /tenants/{id}/newsletters` (onderwerp, datum, status, ESP,
      template, gesprek-id) en `GET .../newsletters/{id}` (html voor preview).
- [x] **Deeplink per ESP** in het antwoord van `create_newsletter_draft` en in
      de lijst. Exacte URL-paden per platform verifiëren met een bestaand
      concept voordat we ze vastleggen.
- [x] Tab "Nieuwsbrieven" met lijst, preview-iframe, knop "Open in {ESP}" en
      "Gebruik als basis" (start een gesprek met de vorige `input` als context).
- [ ] **Testmail** via de ESP-adapter (NIET gebouwd: weekt de 'nooit verzenden'-garantie los, keuze Jeff) waar de API dat toestaat (Brevo
      `sendTest`, ActiveCampaign test-send; Klaviyo checken). Dit is geen
      campagne verzenden; de garantie blijft intact en wordt getest.

## Blok 4: kwaliteitslaag vóór het concept (25 min)

- [x] **CSS-inliner**: `css_inline` (Rust, pip) op de gerenderde HTML vlak voor
      `create_draft`, zodat `<style>`-blokken uit Stripo/AC-exports ook in
      Outlook werken. Aan/uit per tenant (`config.inline_css`, default aan),
      round-trip-test bewaakt dat placeholders en ESP-tags intact blijven.
- [x] **E-mail-checklist** (code, geen LLM): alle `<img>` hebben alt, geen
      `javascript:`-links, unsubscribe-tag van het gekozen ESP aanwezig,
      tekst/beeld-verhouding, onderwerpregel <= 60 tekens, preheader <= 110.
      Resultaat in het preview-antwoord en als blokkade bij het concept voor de
      harde punten (unsubscribe ontbreekt).
- [x] **UTM-parameters**: per tenant `config.utm` (source/medium/campaign-patroon);
      `_require_reachable` plakt ze op uitgaande links ná de 200-check.
- [ ] **Alt-tekst en beschrijving bij afbeelding-upload** (niet gebouwd, schuift door): Haiku 4.5 met
      vision genereert beschrijving + alt + herkent club/product; admin kan
      overschrijven. `list_images` geeft daardoor betere matches.

## Blok 5: model, kosten, gezondheid (15 min)

- [x] **Model**: chat-orchestrator van `claude-sonnet-4-6` naar `claude-sonnet-5`
      (goedkoper per token dan wat nu draait en beter) of `claude-opus-5`
      (hoogste kwaliteit). Keuze Jeff. Tool-proof-transform meelopen.
      `effort` per route opnieuw meten via `mail.llm_usage`.
- [x] SDK pinnen (`anthropic>=0.40` is te los; 1.x heeft breaking changes,
      o.a. httpx2). Eerst vaststellen welke versie in `uv.lock` staat.
- [x] `GET /templates/health` zichtbaar in de Bedrijven-tab (groen/rood per
      bedrijf), zodat een tenant zonder eigen template direct opvalt.

## Blok 6: afronden (10 min)

- [ ] Volledige testrun, `code-reviewer` over de diff, PR's mergen.
- [ ] `/health` op productie na de deploy, één echte chat-beurt met streaming
      op voetbalreizenxl, één template-upload op een testtenant.

---

## Onder de streep (volgende sessie)

- Frontend splitsen in `chat.js`, `templates.js`, `bedrijven.js`,
  `nieuwsbrieven.js` (geen build-stap nodig).
- Rate limiter en validatiecache achter een interface met Postgres-implementatie
  (nu in-memory; breekt stil bij een tweede worker).
- Achtergrondtaken met `procrastinate` (Postgres-queue, geen Redis) voor
  tool-proof van grote templates en tone-analyse.
- Screenshot-preview (Playwright) op Gmail/Outlook-breedte.
- Sentry (`sentry-sdk[fastapi]`) zodra er een DSN is.
- Dekking naar 80%: `esp.py` (0%), `tone.py` (31%), `conversation.py` (45%).
- Meertaligheid: `config.language` in de systeemprompt.

## Moderne tools en imports (waarom deze)

| Tool | Waarvoor | Waarom nu |
|---|---|---|
| `sse-starlette` | SSE-streaming in FastAPI | Tussenstappen in de chat zonder websockets |
| `css_inline` | CSS inlinen vóór verzenden | Rust, snel, Outlook-proof; premailer is verouderd |
| `diff2html` (cdnjs) | Diff-weergave tool-proof | Geen eigen renderer nodig |
| `difflib` (stdlib) | Unified diff server-side | Geen dependency |
| `zipfile` (stdlib) + Supabase Storage | ZIP-import met afbeeldingen | Infra bestaat al |
| Haiku 4.5 vision | Alt-tekst en herkenning bij upload | Cent-werk, grote winst voor `list_images` |
| Sonnet 5 / Opus 5 | Chat en tool-proof | Beter en (Sonnet 5) goedkoper dan huidige 4.6 |
| `selectolax` of `trafilatura` | Pagina's uitkleden vóór extractie | Minder tokens naar Haiku per scrape (onder de streep) |
| `procrastinate` | Postgres-jobqueue | Lange taken uit het request halen (onder de streep) |
| `web_fetch_20260209` (server-tool) | "Lees deze pagina" in de chat | Optioneel; eigen fetch blijft voor de 200-garantie |

Bewust niet: MJML (templates zijn exports, geen bron), Alpine/htmx (vanilla
volstaat na splitsen), Redis (Postgres kan alles wat we nodig hebben).
