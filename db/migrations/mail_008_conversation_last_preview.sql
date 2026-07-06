-- Her-renders erven ontbrekende velden uit de vorige preview-/draft-invoer,
-- zodat een kleine wijziging ("maak de knop zwart") nooit de banner of andere
-- velden kwijtraakt. NULL = nog geen preview gedaan in dit gesprek.
alter table mail.conversations
  add column last_preview jsonb;
