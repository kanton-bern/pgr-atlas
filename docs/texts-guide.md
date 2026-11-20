# Changing the app's texts

How to change a German or French text of PGR-Atlas, or add a French translation, in the
browser. You don't need to program or install anything. You need a GitHub account with access
to the PGR-Atlas repository; ask the maintainers if you don't have one.

Words used here:

- **Repository**: the folder on GitHub that holds the app's code and texts.
- **Pull request**: a proposed change. The maintainers look at it before it goes into the app.
- **Check**: a test GitHub runs on every pull request. It shows a green tick or a red cross.

---

## 1. What this is for

Every text the app shows is in one file: `app/texts.toml`. Each text is there in German and
in French. You change the file in the browser and propose the change. The maintainers check it and put
it into the app.

Every text has French today. **DE | FR** at the bottom of the app's sidebar, under the
version, switches the language. A new text can arrive without French; until it has one, the
app shows it in German in both languages.

## 2. Find a text

1. In the app, note a few words of the text you want to change, e.g. "Berechnete Kacheln".
2. Open the PGR-Atlas repository on GitHub.
3. Press `t` on your keyboard, type `texts.toml` and press Enter. The file opens.
4. Press `Ctrl+F` (`Cmd+F` on a Mac) and type the words from step 1.

The file is ordered like the app: first the texts used everywhere, then the sidebar, then one
part per view (Simulierte Ereignisse, IFK-Berechnung, Raster-Karten, Raster-Derivate, Anriss,
Gebäudeschatten), then texts shared by several views, and last the texts on the maps (part
"Karten": buttons, legends, popups and hover texts). Each part starts with a heading line like
this one:

```toml
# ── IFK-Berechnung ──────────────────────────────────────────────────────────
```

A text shown with a number or a name in it (e.g. "Version 2.3.0") is in the file without
that part. Search for the words around it instead ("Version").

## 3. Anatomy of an entry

A real entry from the file:

```toml
[ifk_area.partly_outside]
note = "The selected area reaches beyond the finished Kacheln."
de = "Das Gebiet liegt teilweise ausserhalb der berechneten Kacheln ({n_missing} von {n_kacheln} km² Kacheln ohne Daten) - die Kurven decken nur den berechneten Teil ab."
fr = "La zone dépasse en partie les tuiles calculées ({n_missing} tuiles de km² sur {n_kacheln} sans données) - les courbes ne couvrent que la partie calculée."
```

| Part | What it is | Change it? |
|---|---|---|
| `[ifk_area.partly_outside]` | The **key**: the text's name. The app asks for the text by this name | **No** |
| `note = "…"` | A note in English for the translator: where the text appears, what it means | No (ask the maintainers if it is unclear) |
| `de = "…"` | The German text | **Yes**, the part between the quotes |
| `fr = "…"` | The French text. `fr = ""` means not yet translated: the app shows the German | **Yes**, the part between the quotes |
| `{n_missing}`, `{n_kacheln}` | **Placeholders**. The app puts a number or a name there when it shows the text | **No**: keep each one exactly. You may move it within the sentence |

Not every entry has a `note`. Some entries have no placeholder.

In the app the example reads, for instance: "Das Gebiet liegt teilweise ausserhalb der
berechneten Kacheln (3 von 12 km² Kacheln ohne Daten) - die Kurven decken nur den berechneten
Teil ab."

## 4. Step by step in the browser

1. Open `app/texts.toml` on GitHub (see section 2).
2. Click the pencil icon at the top right of the file ("Edit this file").


3. Find the text with `Ctrl+F` and change it. Change only the text between the quotes after
   `de =` or `fr =`. You can change several texts in one go.


4. Click the green button **Commit changes…** at the top right.


5. A window opens.
   - In **Commit message**, write in a few words what you changed, e.g. "French for the IFK
     view".
   - Choose **Create a new branch for this commit and start a pull request**. Keep the branch
     name GitHub suggests.
   - Click **Propose changes**.


6. The page "Open a pull request" appears. The title is your message from step 5. Below it,
   you can add a comment for the maintainers, e.g. which texts you are unsure about. Click
   **Create pull request**.


If GitHub says you need to fork the repository first, you don't have write access yet. Stop
there and ask the maintainers.

### What happens next

1. **The check runs** (a few minutes). At the bottom of your pull request you see a yellow dot
   while it runs, then a green tick or a red cross. Red: see section 7.


2. **The maintainers review it.** They read the change, look at long texts in the app on a
   small screen, and may ask a question in the pull request. You get an email from GitHub when
   they comment.
3. **The maintainers merge and deploy it.** Your change goes into the app with the next
   deploy. They tell you when it is live.

## 5. Recipes

### Change a German or French wording

Before:

```toml
[ifk.no_data]
de = "Keine Daten"
fr = "Aucune donnée"
```

After:

```toml
[ifk.no_data]
de = "Keine Daten vorhanden"
fr = "Aucune donnée disponible"
```

Only the text between the quotes changed.

### Add a missing French translation

Every text has French today. A new text can arrive with an empty French line, `fr = ""`.
Fill in the French between the quotes. This is how `nav.raster_derivate` looked before and
after its translation:

Before:

```toml
[nav.raster_derivate]
de = "Raster-Derivate"
fr = ""
```

After:

```toml
[nav.raster_derivate]
de = "Raster-Derivate"
fr = "Dérivés raster"
```

The changed wordings in these recipes are examples, not texts of the app.

### Translate a text with placeholders

Keep each `{…}` exactly as in the German: same name, same braces, nothing translated inside
them. Move it to where the French sentence needs it. This is `startup.manifest_done` before
and after its translation:

Before:

```toml
[startup.manifest_done]
de = "✓ {anriss_count} Anrisse, {pq_count} Prozessquellen, {area_count} Grössenklassen"
fr = ""
```

After:

```toml
[startup.manifest_done]
de = "✓ {anriss_count} Anrisse, {pq_count} Prozessquellen, {area_count} Grössenklassen"
fr = "✓ {anriss_count} zones de déclenchement, {pq_count} sources de processus, {area_count} classes de taille"
```

Wrong: `{nombre_anrisses}` instead of `{anriss_count}`. The check turns red (section 7).

### A text in the app isn't in the file

Some texts come from Streamlit, the toolkit the app is built with, and are not in the file
(see the FAQ). For any other text you can't find:

1. Take a screenshot of the place in the app where you see it.
2. Open a new issue in the repository (tab **Issues**, button **New issue**), with the
   screenshot and the view where you saw it.

The maintainers add the text to the file. A new entry also needs a change to the app that uses it, so you
can't add one yourself: the check turns red for an entry the app doesn't use.

### Send the whole file to a translation service

1. Open `app/texts.toml` on GitHub and click the download icon ("Download raw file") at the
   top right of the file.


2. Send the file to the translation service with these instructions: translate the text
   between the quotes after `fr =`, using the German after `de =` and the `note`; change
   nothing else; keep every `{…}` as it is; the file must stay UTF-8.
3. When the file comes back, open `app/texts.toml` on GitHub, click the pencil icon, select
   everything in the editor (`Ctrl+A`), delete it, and paste the content of the returned file.
4. Continue with step 4 of section 4.

Do this soon after downloading: if the maintainers added texts in the meantime, pasting an older file
removes them, and the check turns red. If that happens, comment on the pull request and the
maintainers sort it out.

## 6. The rules in one box

> - Every text starts and ends with a straight double quote: `"…"`.
> - A double quote inside a text is written `\"`, e.g. `de = "Die Option \"Alle\" wählen"`.
>   A backslash `\` is written `\\`. French apostrophes (`'` or `’`) need nothing special.
> - Keep `\n` (a line break) and everything between `$` signs (a formula) as they are.
> - Don't change, rename or remove a key (the line in `[…]`), a `note =` / `de =` / `fr =`
>   label, or a placeholder (`{…}`).
> - Every entry keeps its `fr = ` line, even when the French is empty: `fr = ""`.
> - French spacing goes in the text: if you want a space before `:` `;` `?` `!`, type it.
>   The app adds nothing.
> - `**word**` shows the word in bold. Keep the stars in the German, and put them around the
>   matching words in the French.
> - No HTML.

## 7. When the check is red

Click **Details** next to the red cross. GitHub opens the log of the check. Scroll to the step
**Pytest** and look for a line that names `texts.toml`, or one starting with `FAILED`. The three
common messages follow, quoted from the real test output.

If none of this helps, write a comment on the pull request ("the check is red") and the maintainers fix it.

### A quote is missing

```text
ValueError: texts.toml can't be read: Illegal character '\n' (at line 283, column 21). Look at that line: each text starts and ends with a quote ("), and a quote inside a text is written \".
```

The text on line 283 has no closing quote, e.g. `fr = "Pas de données`. "Illegal character"
can name another character; the line number is what matters.

To fix it in your pull request:

1. On the pull request, open the tab **Files changed**.
2. Click the three dots (`…`) at the right of `app/texts.toml` and choose **Edit file**.
3. Go to the line the message names (the line numbers are on the left) and add the missing
   `"`. If the text contains a `"`, write it as `\"`.
4. Click **Commit changes…**, keep **Commit directly to the … branch** selected, and click
   **Commit changes**. The check runs again.


### A placeholder doesn't match

```text
`fr` of "ifk_area.partly_outside" uses {n_kacheln}, {nombre}, but the German uses {n_kacheln}, {n_missing}. Keep the placeholders exactly as in German.
```

The French text of `ifk_area.partly_outside` has `{nombre}` where the German has
`{n_missing}`. To fix: replace `{nombre}` with `{n_missing}` in the `fr` line. A French text
must have the same placeholders as the German, no more and no fewer.

### An unknown or missing key

The key in `[…]` was changed or removed. The app asks for every text by its key, so it can't
find the text anymore. The message names the key:

```text
app/ifk_charts.py:103 uses "ifk.no_data", which is not in app/texts.toml. Add the entry, or fix the key.
"ifk.no_date" is in app/texts.toml but the app never shows it. Remove it, or ask the maintainers to use it.
```

To fix: change the key back to how it was (here `[ifk.no_date]` back to `[ifk.no_data]`). If
you didn't touch any key, comment on the pull request: it's for the maintainers to fix.

## 8. What's left to translate

Every pull request that changes the file also prints how many texts have French, and lists
any that have none yet:

1. On your pull request, click **Details** next to the check **unit**.
2. Open the step **Texts missing in French**.

Today every text has French, so it prints one line:

```text
490 texts, 490 with French.
```

When texts are missing, a line `Missing in French (n):` follows, then one key per line.
Search for each key in the file with `Ctrl+F`.


## 9. FAQ

**When is my change live?** After the maintainers have reviewed and merged your pull request,
with the next deploy of the app. They tell you when it is live.

**Can I break the app?** No. The check stops a broken file before it is merged. At worst your
pull request shows a red cross until the file is fixed.

**Why is this button still in English?** Some texts come from Streamlit, the toolkit the app
is built with: for example the file upload box and "Press Enter to submit form". Streamlit has
no setting for them, so they stay English in both languages.

**Why don't the names of downloaded files and the column names in CSV files change with the
language?** They stay the same in both languages on purpose, so scripts and spreadsheets that
read them keep working.

**Why are numbers written differently in French?** The app writes every number for the
language shown: 2'584.5 in German, 2 584,5 in French. A placeholder gets its number already
written that way, so a translation never contains a number of its own. Numbers in downloaded
files stay as in German.

**Can I edit several texts in one pull request?** Yes. One pull request for a batch of changes
is easier to review than many small ones.

**I made a mistake after creating the pull request.** Edit the file again on your pull
request (see section 7, "A quote is missing", steps 1 to 4), or comment on
the pull request and the maintainers fix it.
