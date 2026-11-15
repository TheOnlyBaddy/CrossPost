import { Connections } from "./Connections";
import { SetupBanner } from "./SetupBanner";
import type { Health } from "../types";

/**
 * Shown after sign-in while nothing is connected. Once a platform is live this
 * step disappears and the connections live in the sidebar instead, so it never
 * becomes a page you have to click through every time.
 */
export function ConnectPage({
  health,
  showPagePicker,
  onChanged,
  onSkip,
}: {
  health: Health;
  showPagePicker: boolean;
  onChanged: () => void;
  onSkip: () => void;
}) {
  return (
    <main className="connect">
      <div className="connect-inner">
        <header className="connect-head">
          <h1>Connect where you post</h1>
          <p>
            One Meta login covers Facebook and Instagram. You can add the rest
            later — nothing publishes until you say so.
          </p>
        </header>

        <Connections
          health={health}
          showPagePicker={showPagePicker}
          onChanged={onChanged}
        />

        <SetupBanner health={health} />

        <button type="button" className="btn btn-ghost btn-block" onClick={onSkip}>
          Skip for now
        </button>
      </div>
    </main>
  );
}
