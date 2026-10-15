# Vantage 1.44.135: saved reference tools on your phone

The permanent [Vantage phone app](https://vantageupdates.github.io/vantage/companion/)
can reopen from the Home Screen when the PC is off or its local Wi-Fi address is
unavailable, after the app and catalogs have finished saving on that phone.

## What is available

- Market and Spells use the last catalog successfully saved on the phone.
- Zones and Quests include searchable bundled names and links to their Wiki
  pages. These indexes do not contain every full Wiki article. Opening a Wiki
  link requires an internet connection.
- Guild shows the selected guild's last imported standings, loot, raids, and
  supported Google Sheets links. The standing search includes every exported
  character, including names beyond the old first 250 results. The export has
  a 10,000-standing safety limit and identifies shortened collections.
- A private PC snapshot also includes the currently loaded zone and quest
  details. Other zone or quest details are not automatically downloaded.
- EQ Live, PC timer controls, current buffs, and changes to the PC selection
  continue to use the private Mobile Host link on the same Wi-Fi.

Guild and reference details are saved copies. The export time means when the
file was prepared; it does not mean the guild or Wiki source was refreshed then.
Live auctions are not included.

## Install once, then save your private records

1. Open the permanent phone app while the phone is online. On iPhone, use Safari,
   choose Share, Add to Home Screen, and enable Open as Web App. On Android, use
   the browser's Install app or Add to Home screen command.
2. Open the installed app while online and wait for its offline-ready status.
   Installing the private HTTP Mobile Host page does not give the same cold-start
   offline behavior on a phone.
3. Start Vantage's Mobile Host on the PC and open its private QR link on the same
   Wi-Fi. Load the guild and any zone or quest details you want to save.
4. In the phone's private PC view, select Phone App, then Save to phone app.
   Review the records in the permanent app and explicitly confirm the import.
5. Check the saved records inside the installed Home Screen app. If the browser
   blocked the transfer, or the saved records are not present there, use Download
   private snapshot in the PC view. Inside the installed app, open Saved & Help,
   use Choose Vantage offline file, and select `vantage-private-offline.json`.
   The Guild section's Import copy button also takes you to that control. Review
   the copy, then choose Save this copy.

Safari and an installed iPhone web app can keep separate storage. Importing a
file inside the installed app avoids depending on storage sharing between them.
Imports replace the saved snapshot after confirmation; they do not update the PC.

## Privacy and limits

The private export contains only selected guild records and display fields from
the current zone and quest. It excludes pairing keys, login credentials, raw EQ
logs, local file paths, game images, and live timers or buffs. Only canonical
Google Sheets document links are retained, with query strings and fragments
removed. Unsupported sheet links are omitted.

The export requires the same private authorization as the PC view. The phone
handoff transfers a bounded JSON snapshot between the two browser windows; it
does not upload the snapshot or the private PC connection key to a service. The
permanent phone app does not store the private PC pairing URL. Downloaded JSON
files still contain your guild records: keep them private and delete unwanted
copies using your phone's file manager.

The total snapshot limit is 8 MiB, with additional limits on individual fields
and collections. Shortened collections are reported during import. A malformed,
unsupported, or too-large file is rejected without replacing the previous saved
snapshot. No browser storage is a backup: clearing site data, uninstalling the
app, or storage eviction can remove saved records. Reconnect once to restore the
app's catalogs and import your private snapshot again when needed.

For a practical offline check, open each saved section in the installed app,
close it, turn the PC off or disconnect the phone from Wi-Fi, and reopen the
Home Screen icon. Market, Spells, indexes, and imported records should open;
current PC tools require reconnecting to the private local link.
