import { useEffect, useState } from 'react';
import { LoaderCircle, X } from 'lucide-react';

// Mount for one pending operation; finishing or leaving its page clears the timer.
export default function LongWaitNotice({ activity }: { activity: string }) {
  const [visible, setVisible] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setVisible(true), 8000);
    return () => window.clearTimeout(timer);
  }, []);
  if (!visible || dismissed) return null;
  return (
    <aside className="long-wait-notice" aria-label="Progress update">
      <div role="status">
        <LoaderCircle className="spin" size={22} aria-hidden="true" />
        <div>
          <strong>Still working on it</strong>
          <p>{activity} This may take a little longer. Thanks for your patience.</p>
          <p>Please keep this page open while you wait.</p>
        </div>
      </div>
      <button type="button" aria-label="Dismiss progress update" onClick={() => setDismissed(true)}>
        <X size={18} />
      </button>
    </aside>
  );
}
