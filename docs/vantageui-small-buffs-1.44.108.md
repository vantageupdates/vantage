# VantageUI 1.44.108 (H): smaller buff panel

The user reported107's1066×100 horizontal window as too wide, then narrowed
the request to simply making it smaller. This release changes the fixed layout
to576×168, using two short rows (8+7). It is approximately46% narrower and9%
smaller in outer area, but68px taller. It is not free resizing, scrolling,
automatic reflow or active-buff compaction.

Native24×24 icons,20×20 decals, Font1,66×40 centered wrapping name lanes,
1px shadows, spell artwork and all native bindings remain. Column pitch70px,
row pitch72px; icon offsets27,4 and name offsets6,30 within each cell.
The conservative native client is568×144. The last visible shadow ends at143.

All25 original control definitions and their IDs/EQTypes/Pieces are preserved.
The first15 fill8 cells then7. Extra definitions15–24 begin on row2 or later,
beyond the visible pane; they never occupy the unused sixteenth visible cell.
There is no additional P99 buff capacity. Short-duration effects are unchanged.
The native titlebar remains the drag area. The vertical104 preset and the
previous105/106/107 published horizontal releases are immutable and untouched.

With EverQuest closed, run this release's VantageUI-Updater.exe, choose
**Buff hotkeys…**, and wait for both folders to be verified. Create/update the
two socials manually using these first-line commands:

| Option | Identification | Command |
| --- | --- | --- |
| Vertical | 1.44.104 (V) | `/loadskin VantageUI-v1.44.104 1` |
| Horizontal | 1.44.108 (H) | `/loadskin VantageUI-v1.44.108 1` |

Commands reload the whole skin with settings preserved. The updater does not
write socials or character INIs, load a skin or replace edited/unknown folders.
Migration from105/106/107 upgrades to verified108, prepares104 through the
narrow verified-current-H exception, then reselects108. Ordinary downgrades
stay refused. Old registered presets are retained. Interrupted preparation
does not claim that both layouts are ready. Older updater builds may prepare
older pairs; use this release's executable for104/108.

The private preview is an XML/assets approximation, not a native P99 render.
Sample fonts/mappings are approximate. The screenshot's compound name
JourneymanBoots has no space; its exact native wrapping is not guaranteed by
the preview. Actual108 icon/name placement, Font1 wrapping, saved-size reload,
hover/tooltips, dragging and right-click cancellation require an in-game check.
No engine-level scaling or HD change is claimed. Companion/main, installed
executables, running game processes, live skins and game settings are untouched.
