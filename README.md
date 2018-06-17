# MarcoPolo

Poloniex trading instance that may be deployed from a core analysis module.

1) Create trade with desired parameters
2) Trade added as MongoDB entry
3) Core program handles market checks and trade execution for all active entries
4) Entries removed from active trade collection once stopped-out or target sell executed

- Calculate/recalculate trailing-stop, if applicable

<b>To Do:</b>
- Create "off-book" price monitoring/order execution
-- Websockets?

<b>Needs Testing:</b>
-

<b>Done:</b>
-
