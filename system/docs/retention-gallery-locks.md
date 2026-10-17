# Retention and gallery lock ordering

The October 14 live stack dump showed build-retention waiting inside
`built_mods.current()` while holding the global Store RLock. A gallery refresh
held its cache mutex while waiting in `store.get()`. The local LLM route then
called its synchronous operator gate from the asyncio loop and waited on the
same Store lock, making even health requests stop responding.

Retention now obtains worker and gallery snapshots before entering its Store
transaction. It re-reads the current policy, running sessions and pending jobs
inside the transaction, preserving serialized cleanup decisions and allowing
slider changes to cancel old queued decisions. Neither the periodic sweep nor
the settings endpoint wraps the gallery call in Store.

The LLM's operator checks run in a worker thread, including the second check
after acquiring the model slot. Cancellation during that check releases the
slot. Slow database access must not freeze the HTTP event loop.

Regression checks exercise an intentionally blocked gallery with a concurrent
Store write, a slow operator gate with a timer on the serving loop, and
cancellation during the second gate. Existing retention protection and LLM
queue/gating tests remain applicable. This repairs future calls after runtime
activation; syncing source cannot release locks already held by the old process.
