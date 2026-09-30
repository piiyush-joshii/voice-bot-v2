import { useState } from "react";
type Props = {
  disabled: boolean;
  captureActive: boolean;
  onSend: (text: string) => void;
};

export function TextInput({ disabled, captureActive, onSend }: Props) {
  const [value, setValue] = useState("");
  const blocked = disabled || captureActive;
  return (
    <form
      className="text-input"
      onSubmit={(e) => {
        e.preventDefault();
        const t = value.trim();
        if (!t || blocked) return;
        onSend(t);
        setValue("");
      }}
    >
      <label htmlFor="user-text">Message</label>
      <div className="row">
        <input
          id="user-text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          disabled={blocked}
          placeholder={captureActive ? "Chat paused while the secure form is open" : "Type a message, then Send"}
        />
        <button type="submit" className="primary" disabled={blocked || !value.trim()}>
          Send
        </button>
      </div>
      {captureActive && <p className="hint">Text is rejected server-side during SECURE_CAPTURE.</p>}
    </form>
  );
}
