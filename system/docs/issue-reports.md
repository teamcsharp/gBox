# Issue reports

Choose **Capture → Report issue** to open a popup with a subject and issue details. Opening or cancelling the form does not submit a report. **Send report** creates one inbox request containing your text, attachments, the pre-form screenshot and available game diagnostics.

Paste images or copied files with Ctrl+V, drop files onto the form, or use **Add files…**. **Paste files** also reads files copied in Windows File Explorer. Markdown, binary files and other formats are retained as files with their original names and bytes. Text copied from a document still pastes normally into the subject or issue field. Attachments can be reviewed and removed before sending.

Up to 18 user files can be attached, reserving the server's remaining two attachment slots for diagnostics. Folders are not traversed; copy individual files. If attaching or sending fails, the draft remains open and the error is shown. Fix/retry the attachment operation before sending, so a failed attachment cannot silently disappear from the report.

Validation: 12 Electron checks covered opening without submission, image/Markdown/binary paste, normal text paste, File Explorer clipboard files, failure recovery, successful submission, subject/details, byte preservation, diagnostics and cancellation. The API regression test downloads each uploaded attachment and compares its bytes with the original.


The report dialog can be moved by its heading or Alt+drag and resized from its edges/corners. Saved placement is clamped to the current viewport on reopening or resizing the application. Closing the dialog releases its drag listeners. Native mouse/keyboard validation covers sustained dragging, corner resizing, small-viewport recovery and rapid text entry.
