import { useRef, useState, DragEvent, ChangeEvent } from 'react';

interface Props {
  multiple?: boolean;
  accept?: string;
  label?: string;
  onFilesSelected: (files: File[]) => void;
  disabled?: boolean;
}

/**
 * Drag-and-drop + click-to-browse file input component.
 * Shows a preview grid of selected images.
 */
export default function PhotoDropzone({
  multiple = false,
  accept = 'image/jpeg,image/png,image/webp,image/heic',
  label = 'Drop photos here or click to browse',
  onFilesSelected,
  disabled = false,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [previews, setPreviews] = useState<string[]>([]);
  const [allFiles, setAllFiles] = useState<File[]>([]);

  function processFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    const arr = Array.from(files);
    const next = multiple ? [...allFiles, ...arr] : arr;
    setAllFiles(next);
    onFilesSelected(next);
    const urls = arr.map((f) => URL.createObjectURL(f));
    setPreviews((prev) => (multiple ? [...prev, ...urls] : urls));
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    if (!disabled) processFiles(e.dataTransfer.files);
  }

  function onDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    if (!disabled) setDragging(true);
  }

  function onChange(e: ChangeEvent<HTMLInputElement>) {
    processFiles(e.target.files);
    // Reset input so the same file can be re-selected after removal
    e.target.value = '';
  }

  function clearPreviews() {
    previews.forEach((url) => URL.revokeObjectURL(url));
    setPreviews([]);
    setAllFiles([]);
    onFilesSelected([]);
  }

  return (
    <div className="dropzone-wrapper">
      <div
        className={`dropzone ${dragging ? 'dropzone--active' : ''} ${disabled ? 'dropzone--disabled' : ''}`}
        onClick={() => !disabled && inputRef.current?.click()}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={() => setDragging(false)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
        aria-label={label}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          onChange={onChange}
          style={{ display: 'none' }}
          disabled={disabled}
        />
        <div className="dropzone__icon">📷</div>
        <p className="dropzone__label">{label}</p>
        <p className="dropzone__hint">JPEG, PNG, WebP or HEIC — max 20 MB each</p>
      </div>

      {previews.length > 0 && (
        <div className="preview-section">
          <div className="preview-header">
            <span>{previews.length} photo{previews.length !== 1 ? 's' : ''} selected</span>
            <button type="button" className="btn-link" onClick={clearPreviews}>
              Clear
            </button>
          </div>
          <div className="preview-grid">
            {previews.map((url, i) => (
              <img
                key={i}
                src={url}
                alt={`Preview ${i + 1}`}
                className="preview-thumb"
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
