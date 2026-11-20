// Thin loader. index.js keeps a fixed filename (www/planning-app.html points at it), so
// everything the page chunks share must live in content-hashed chunks instead: if a page
// chunk imported "../index.js" it would get a stale cached copy after a deploy (the old
// menu, old API helpers). Keeping the entry this small means nothing imports it.
import('./bootstrap.js')
