# Skill: /newsletter

Genereer kant-en-klare nieuwsbrief-HTML voor ActiveCampaign op basis van recente LinkedIn-posts.

## Aanroep

```
/newsletter {klant}
/newsletter {klant} --posts {aantal}
```

Voorbeelden:
- `/newsletter dunion`
- `/newsletter dunion --posts 6`

Als `--posts` ontbreekt, gebruik de `default_posts` uit de configuratie van de klant.

---

## Stappen die je uitvoert

### 1. Lees klantconfiguratie

Lees het bestand:
```
clients/{klant}/newsletter-config.json
```

Haal hieruit: `linkedin_url`, `default_posts`, `client_name`.

Als het bestand niet bestaat, meld je dat aan de gebruiker en stop je.

### 2. Bepaal aantal posts

Gebruik `--posts` als opgegeven, anders `default_posts` uit de config.
Het aantal moet altijd **even** zijn (2, 4 of 6) voor het 2-koloms grid. Als een oneven getal wordt opgegeven, rond je af naar boven.

### 3. Haal LinkedIn-posts op via Apify

Voer het volgende uit via Bash vanuit de Email Marketing-map:

```bash
python tools/fetch_linkedin_posts.py --url "{linkedin_url}" --posts {aantal}
```

De actor `supreme_coder/linkedin-post` haalt de meest recente posts op van de bedrijfspagina. Geen cookies vereist.

De output is een JSON-array met per post: `text`, `imageUrl`, `postUrl`.

- `text`: volledige posttekst (inclusief Unicode-opmaak)
- `imageUrl`: URL van de afbeelding of eerste slide van een carousel; kan leeg zijn
- `postUrl`: directe LinkedIn-URL naar de post

Als het script een fout geeft of de array leeg is, meld dit duidelijk aan de gebruiker en stop.

Als een post geen `imageUrl` heeft, neem die post niet mee en haal een extra post op door `--posts` te verhogen met 1 en het script opnieuw te draaien.

### 4. Herschrijf de teksten

Herschrijf voor elke post de `text` naar een compacte nieuwsbrieftekst van **maximaal 3 zinnen**.

Zorg dat alle teksten binnen een rij **vergelijkbare lengte** hebben zodat de knoppen op gelijke hoogte komen.

Stijlregels:
- Zakelijk maar toegankelijk Nederlands
- Geen emojis
- Geen em-dashes (gebruik komma of dubbele punt)
- Behoud de kernboodschap van de originele post
- Verwijder Unicode-vetdruk en andere opmaaktekens uit de tekst

### 5. Bouw de HTML

Lees het template:
```
clients/{klant}/newsletter-template.html
```

Genereer per rij van 2 posts de volgende HTML (herhaal voor elke rij). Let op `height="100" valign="top"` op de tekstcel voor gelijke uitlijning van de knoppen:

```html
<tr>
    <td class="esd-structure es-p20t es-p10b es-p20r es-p20l" align="left" bgcolor="#ffffff" style="background-color: #ffffff;">
        <!--[if mso]><table width="610" cellpadding="0" cellspacing="0"><tr><td width="295" valign="top"><![endif]-->
        <table cellpadding="0" cellspacing="0" class="es-left" align="left">
            <tbody>
                <tr>
                    <td width="295" class="esd-container-frame es-m-p20b" align="left">
                        <table cellpadding="0" cellspacing="0" width="100%" style="border-left: 1px solid #cccccc; border-right: 1px solid #cccccc; border-bottom: 1px solid #cccccc;">
                            <tbody>
                                <tr>
                                    <td align="center" class="esd-block-image" style="font-size: 0px;">
                                        <a target="_blank" href="{postUrl_links}">
                                            <img class="adapt-img" src="{imageUrl_links}" alt="" style="display: block;" width="293">
                                        </a>
                                    </td>
                                </tr>
                                <tr>
                                    <td align="left" class="esd-block-text es-p10t es-p20b es-p20r es-p20l" height="100" valign="top">
                                        <p>{tekst_links}</p>
                                    </td>
                                </tr>
                                <tr>
                                    <td align="left" class="esd-block-button es-p20t es-p30b es-p20r es-p20l" bgcolor="#ffffff">
                                        <!--[if mso]><a href="{postUrl_links}" target="_blank" hidden>
  <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" esdevVmlButton href="{postUrl_links}"
            style="height:36px; v-text-anchor:middle; width:191px" arcsize="0%" stroke="f" fillcolor="#ff7e00">
        <w:anchorlock></w:anchorlock>
        <center style='color:#ffffff; font-family:tahoma, verdana, segoe, sans-serif; font-size:12px; font-weight:700; line-height:12px; mso-text-raise:1px'>Meer informatie</center>
  </v:roundrect></a>
<![endif]-->
                                        <!--[if !mso]><!-- --><span class="msohide es-button-border" style="border-color: #2090fe; border-radius: 0px; background: #ff7e00;"><a href="{postUrl_links}" class="es-button" target="_blank" style="font-family: tahoma, verdana, segoe, sans-serif; padding: 10px 30px; color: #ffffff; background: #ff7e00; border-radius: 0px; font-weight: bold; mso-border-alt: 10px solid #ff7e00">Meer informatie</a></span>
                                        <!--<![endif]-->
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </td>
                </tr>
            </tbody>
        </table>
        <!--[if mso]></td><td width="20"></td><td width="295" valign="top"><![endif]-->
        <table cellpadding="0" cellspacing="0" class="es-right" align="right">
            <tbody>
                <tr>
                    <td width="295" align="left" class="esd-container-frame">
                        <table cellpadding="0" cellspacing="0" width="100%" style="border-left: 1px solid #cccccc; border-right: 1px solid #cccccc; border-bottom: 1px solid #cccccc;">
                            <tbody>
                                <tr>
                                    <td align="center" class="esd-block-image" style="font-size: 0px;">
                                        <a target="_blank" href="{postUrl_rechts}">
                                            <img class="adapt-img" src="{imageUrl_rechts}" alt="" style="display: block;" width="293">
                                        </a>
                                    </td>
                                </tr>
                                <tr>
                                    <td align="left" class="esd-block-text es-p10t es-p20b es-p20r es-p20l" height="100" valign="top">
                                        <p>{tekst_rechts}</p>
                                    </td>
                                </tr>
                                <tr>
                                    <td align="left" class="esd-block-button es-p20t es-p30b es-p20r es-p20l" bgcolor="#ffffff">
                                        <!--[if mso]><a href="{postUrl_rechts}" target="_blank" hidden>
  <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" esdevVmlButton href="{postUrl_rechts}"
            style="height:36px; v-text-anchor:middle; width:191px" arcsize="0%" stroke="f" fillcolor="#ff7e00">
        <w:anchorlock></w:anchorlock>
        <center style='color:#ffffff; font-family:tahoma, verdana, segoe, sans-serif; font-size:12px; font-weight:700; line-height:12px; mso-text-raise:1px'>Meer informatie</center>
  </v:roundrect></a>
<![endif]-->
                                        <!--[if !mso]><!-- --><span class="msohide es-button-border" style="border-color: #2090fe; border-radius: 0px; background: #ff7e00;"><a href="{postUrl_rechts}" class="es-button" target="_blank" style="font-family: tahoma, verdana, segoe, sans-serif; padding: 10px 30px; color: #ffffff; background: #ff7e00; border-radius: 0px; font-weight: bold; mso-border-alt: 10px solid #ff7e00">Meer informatie</a></span>
                                        <!--<![endif]-->
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </td>
                </tr>
            </tbody>
        </table>
        <!--[if mso]></td></tr></table><![endif]-->
    </td>
</tr>
```

Wikkel alle rijen in:
```html
<td class="esd-stripe" align="center">
    <table bgcolor="#ffffff" class="es-content-body" align="center" cellpadding="0" cellspacing="0" width="650">
        <tbody>
            {alle rijen hier}
        </tbody>
    </table>
</td>
```

### 6. Sla op

Sla de gegenereerde HTML op als:
```
clients/{klant}/newsletters/nieuwsbrief_YYYY-MM-DD.html
```

Gebruik de datum van vandaag in de bestandsnaam.

Bevestig aan de gebruiker dat het bestand is opgeslagen en geef het volledige pad.

---

## Nieuwe klant toevoegen

Voor een nieuwe klant zijn twee bestanden vereist:

1. `clients/{klant}/newsletter-config.json`
   ```json
   {
     "client_name": "Naam van de klant",
     "linkedin_url": "https://www.linkedin.com/company/linkedin-slug-van-klant/",
     "default_posts": 4
   }
   ```

2. `clients/{klant}/newsletter-template.html`
   Kopieer het Dunion-template en pas de huisstijlkleuren aan (knoppen, achtergrond, etc.).

---

## Veelvoorkomende problemen

- **APIFY_API_KEY ontbreekt**: Voeg de sleutel toe aan `.env`
- **"no available accounts found"**: De actor `supreme_coder/linkedin-post` gebruikt een gedeelde pool van LinkedIn-accounts om bedrijfspagina's te scrapen. Als die pool tijdelijk leeg is, geeft het script deze fout. Dit is een tijdelijk probleem van de actor. Meld aan de gebruiker dat ze het over een uur opnieuw kunnen proberen.
- **0 posts gevonden (andere reden)**: Controleer of de LinkedIn-URL in de config correct is en of de bedrijfspagina publiek toegankelijk is.
- **Afbeelding laadt niet in e-mail**: LinkedIn CDN-URLs verlopen na enkele weken; upload afbeeldingen naar ActiveCampaign en vervang de URLs voor verzending
