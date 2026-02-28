/**
 * Free/personal/disposable email domains.
 *
 * This list is intentionally data-only so we can expand it over time without
 * touching flow logic. It includes high-signal providers and disposable domains
 * from product requirements.
 */

const RAW_FREE_EMAIL_DOMAINS = `
0-mail.com
10minutemail.co.za
20mail.it
aol.com
att.net
gmail.com
googlemail.com
hotmail.ca
hotmail.co.uk
hotmail.com
icloud.com
live.com
mail.com
me.com
msn.com
outlook.com
outlook.co.uk
pm.me
proton.me
protonmail.com
yahoo.ca
yahoo.co.uk
yahoo.com
yandex.com
yandex.ru
ymail.com
zoho.com
163.com
126.com
qq.com
naver.com
daum.net
hanmail.net
gmx.com
gmx.de
mail.ru
inbox.ru
list.ru
bk.ru
rambler.ru
fastmail.com
tutanota.com
hey.com
mailinator.com
mailinator.org
mailinator.us
temp-mail.com
temp-mail.de
tempmail.us
tempmail2.com
temporaryemail.us
mytemp.email
throwam.com
yopmail.com
discard.email
dropmail.me
spambob.com
spambob.org
spamex.com
fake-mail.cf
fake-mail.ga
fake-mail.ml
maildrop.cc
maildrop.gq
sharklasers.com
guerrillamail.com
guerrillamailblock.com
guerrillamail.biz
guerrillamail.de
pokemail.net
trash-mail.ga
trash-mail.ml
trashdevil.de
wegwerfmail.info
wegwerf-emails.de
burnthespam.info
mailforspam.com
spamfree24.info
spamfree24.net
nospammail.net
getairmail.com
getairmail.cf
getairmail.ga
getairmail.gq
inbox.com
hushmail.com
rocketmail.com
rediffmail.com
sina.com
sohu.com
yeah.net
seznam.cz
web.de
freenet.de
libero.it
virgilio.it
orange.fr
wanadoo.fr
laposte.net
sapo.pt
tiscali.it
bol.com.br
uol.com.br
globomail.com
`;

export const FREE_EMAIL_DOMAINS: ReadonlySet<string> = new Set(
  RAW_FREE_EMAIL_DOMAINS
    .split('\n')
    .map((d) => d.trim().toLowerCase())
    .filter(Boolean)
);

/**
 * Known wildcard-ish families from the supplied deny list.
 */
const FREE_EMAIL_DOMAIN_PATTERNS: ReadonlyArray<RegExp> = [
  /^mail2.*\.com$/i,
  /^mail.*\.ru$/i,
  /^.*\.rr\.com$/i,
  /^temp.*mail/i,
  /^trash.*mail/i,
  /^.*mailinator\./i,
];

export function isFreeOrPrivateEmailDomain(domain: string): boolean {
  const normalized = domain.trim().toLowerCase();
  if (!normalized) return false;
  if (FREE_EMAIL_DOMAINS.has(normalized)) return true;
  return FREE_EMAIL_DOMAIN_PATTERNS.some((pattern) => pattern.test(normalized));
}
