"""OCR accuracy guidance shown on the Tips tab and in the start-up reminder."""

# One entry per tip, most important first. The start-up reminder numbers them;
# the Tips tab shows the same text as a bulleted list.
ACCURACY_TIP_ITEMS = (
    "Make the combat window wide enough that every message, even the longest, stays on one line. "
    "A message that wraps onto a second line is read as two fragments and its damage can be lost.",

    "IMPORTANT: leave a clear margin on every side when you draw the capture region, especially on the "
    "left. Start the box about a finger's width (20 to 30 pixels) left of where the text begins, and keep "
    "a similar gap above the top line, below the bottom line, and past the end of the longest line. If the "
    "left edge sits right on the text, a one-pixel shift of the game window or a frame caught mid-redraw "
    "cuts off the first letter of every name, so \"Playername\" is read as \"layername\". Never cut through the "
    "top, bottom, or sides of letters; include the complete height and width of every line.",

    "Use a black, fully opaque combat-window background. Transparency lets the game world bleed "
    "through the letters.",

    "The more people fighting, the taller the window must be. Multi-hit abilities such as Frenzy and "
    "Flurry produce bursts of lines that scroll out before the next scan in a short window. A full group "
    "needs a tall window; for top accuracy in a raid, close to half the screen may be combat log. A faster "
    "scan interval helps too.",

    "Font size: try /chatfontsize 5 in game and adjust from there. You want the font just big enough "
    "that OCR reads every character clearly, and no bigger, because a larger font wraps long messages "
    "onto two lines and fills the window with fewer lines. Size 5 reads as accurately as size 6 in "
    "testing while keeping more messages on one line.",

    "Keep the mouse pointer, other windows, and tooltips out of every OCR capture region while "
    "monitoring. Anything drawn over the chat replaces the letters underneath. Discord Overlay repairs "
    "words the cursor hides using recently seen lines, marked with ~ in the Log, but it never guesses "
    "hidden numbers.",

    "Arrange timer overlays outside every OCR capture region. Click-through stops them from "
    "intercepting input, but visible overlay pixels still cover combat text if the windows overlap.",

    "For the most accurate group numbers, turn on the Group filter in Settings and list every "
    "player and pet name in your group. Fights are then counted only when one side is you or a "
    "listed name, so passers-by fighting nearby are excluded. Mobs do not need to be listed. The "
    "list is saved per character.",

    "Reduce unnecessary combat spam when possible. If you do not need them for parsing or "
    "triggers, hide messages such as melee misses so important damage, healing, and mechanic lines "
    "stay visible longer.",
)

ACCURACY_TIPS = "\n\n".join(f"• {tip}" for tip in ACCURACY_TIP_ITEMS)
