'use strict';

// Capture only the owned PiP's rendered content. This works for cross-origin
// MJPEG images without granting the page access to another window or desktop.
async function capture(win, event, rect, compact) {
  if (!compact || !win || win.isDestroyed() || event.sender !== win.webContents ||
      event.senderFrame !== win.webContents.mainFrame) throw Error('Only the active PiP can hold its picture.');
  const [width, height] = win.getContentSize();
  if (!rect || !['x','y','width','height'].every(k => Number.isFinite(rect[k])) ||
      rect.x < 0 || rect.y < 0 || rect.width <= 0 || rect.height <= 0 ||
      rect.x + rect.width > width + 1 || rect.y + rect.height > height + 1)
    throw Error('Picture bounds must stay inside the PiP.');
  const area = {x:Math.floor(rect.x),y:Math.floor(rect.y),
    width:Math.min(width-Math.floor(rect.x),Math.ceil(rect.width)),
    height:Math.min(height-Math.floor(rect.y),Math.ceil(rect.height))};
  const image = await win.webContents.capturePage(area);
  if (image.isEmpty()) throw Error('No rendered PiP picture is available.');
  return 'data:image/jpeg;base64,' + image.resize({width:Math.min(960,image.getSize().width)}).toJPEG(85).toString('base64');
}
module.exports = {capture};
