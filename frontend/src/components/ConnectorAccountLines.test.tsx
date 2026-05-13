import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ConnectorAccountLines } from './ConnectorAccountLines';

describe('ConnectorAccountLines', () => {
  it('renders distinct account subtitles and optional avatar (multi-account UI)', () => {
    const { rerender } = render(
      <ConnectorAccountLines
        name="Gmail"
        accountLabel="a@work.com"
        accountIdentifier="a@work.com"
        accountAvatarUrl={null}
      />,
    );
    expect(screen.getByTestId('primary').textContent).toBe('Gmail');
    expect(screen.getByTestId('sub').textContent).toBe('a@work.com');
    expect(screen.queryByTestId('avatar')).toBeNull();

    rerender(
      <ConnectorAccountLines
        name="Gmail"
        accountLabel="b@home.com"
        accountIdentifier="b@home.com"
        accountAvatarUrl="https://example.com/a.png"
      />,
    );
    expect(screen.getByTestId('sub').textContent).toBe('b@home.com');
    expect(screen.getByTestId('avatar').getAttribute('src')).toBe('https://example.com/a.png');
  });
});
