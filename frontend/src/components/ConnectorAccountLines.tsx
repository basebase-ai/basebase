import type { JSX } from 'react';

export interface ConnectorAccountLinesProps {
  name: string;
  accountLabel: string | null;
  accountIdentifier: string | null;
  accountAvatarUrl: string | null;
}

/** Primary + optional account subtitle (used by DataSources multi-account rows). */
export function ConnectorAccountLines(props: ConnectorAccountLinesProps): JSX.Element {
  const { name, accountLabel, accountIdentifier, accountAvatarUrl } = props;
  const sub: string | null = accountLabel ?? accountIdentifier;
  return (
    <div>
      <div className="flex items-center gap-2">
        {accountAvatarUrl ? (
          <img src={accountAvatarUrl} alt="" className="h-4 w-4 rounded-full" data-testid="avatar" />
        ) : null}
        <span data-testid="primary">{name}</span>
      </div>
      {sub ? (
        <span data-testid="sub" className="text-xs text-surface-500">
          {sub}
        </span>
      ) : null}
    </div>
  );
}
