# BlackWatch responsive UI QA

This is the repeatable check for layout regressions. Run it with the UI
available at each viewport width: **320px**, **375px**, **768px**, **1024px**,
**1280px**, and **1440px**.

## Routes

Check Overview, Services, Events, Notifications, Rules, Hosts detail,
Investigations, Tools/IP lookup, and one create/edit form.

## Browser console overflow check

Run this in the browser console on each route:

```js
(() => {
  const html = document.documentElement;
  const body = document.body;
  const viewportOverflow = html.scrollWidth > html.clientWidth || body.scrollWidth > body.clientWidth;
  const scrollables = [...document.querySelectorAll("*")].filter((element) => {
    const style = getComputedStyle(element);
    return /(auto|scroll)/.test(`${style.overflow}${style.overflowX}${style.overflowY}`) &&
      (element.scrollWidth > element.clientWidth || element.scrollHeight > element.clientHeight);
  });
  console.table({
    viewportWidth: window.innerWidth,
    viewportOverflow,
    scrollableRegions: scrollables.length,
    scrollOwners: scrollables.map((element) => element.className || element.tagName),
  });
})();
```

## Expected behavior

- The viewport must not have accidental horizontal overflow.
- The page owns vertical scrolling.
- A wide desktop table may have one horizontal scroll region.
- Mobile card tables must not retain desktop column widths or resize handles.
- Pagination, row actions, dialogs, and mobile navigation must remain reachable.
- JSON and log viewers may scroll internally only when their bounded region is
  intentional and visually clear.
- Long IDs, ARNs, URLs, and notification content must wrap without widening
  the page.
