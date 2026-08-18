/**
 * Route module for the chat pane — discovered by `App.tsx`'s glob, never
 * registered anywhere.
 *
 * The screen is only the pane: the PDF pane is its own route module and the
 * two communicate through the URL query, so a shell may place them side by
 * side without either importing the other.
 */
import { ChatPane } from './ChatPane';

export const path = '/chat';
export const label = 'Chat';
export const order = 20;

export default function ChatRoute() {
  return <ChatPane />;
}
