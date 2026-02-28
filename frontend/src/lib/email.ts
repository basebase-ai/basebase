/**
 * Email validation utilities.
 *
 * Used to enforce work email requirement and extract company domain.
 */

import { isFreeOrPrivateEmailDomain } from '../data/freeEmailDomains';

export function getEmailDomain(email: string): string {
  return email.split('@')[1]?.toLowerCase() || '';
}

export function isPersonalEmail(email: string): boolean {
  const domain = getEmailDomain(email);
  return isFreeOrPrivateEmailDomain(domain);
}

export function suggestCompanyName(domain: string): string {
  return domain
    .replace(/\.(com|co|io|org|net|ai|app|dev|xyz|tech|software|solutions)(\.[a-z]{2})?$/i, '')
    .split(/[.-]/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}
