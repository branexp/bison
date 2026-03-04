-- +goose Up
-- EmailBison integration tables

-- Campaigns table
CREATE TABLE campaigns (
    id INT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    total_leads INT DEFAULT 0,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    last_sync_at TIMESTAMPTZ,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_campaigns_status ON campaigns(status);
CREATE INDEX idx_campaigns_last_sync ON campaigns(last_sync_at);

-- EmailBison leads table
CREATE TABLE emailbison_leads (
    id BIGINT PRIMARY KEY,
    contact_id INTEGER REFERENCES contacts("ContactId") ON DELETE SET NULL,
    email TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    title TEXT,
    company TEXT,
    status TEXT NOT NULL DEFAULT 'unverified',
    tags TEXT[],
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_emailbison_leads_email UNIQUE (email)
);

CREATE INDEX idx_emailbison_leads_contact ON emailbison_leads(contact_id);
CREATE INDEX idx_emailbison_leads_status ON emailbison_leads(status);

-- Contact-campaign junction table
CREATE TABLE contact_campaigns (
    contact_id INTEGER NOT NULL REFERENCES contacts("ContactId") ON DELETE CASCADE,
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    lead_id BIGINT NOT NULL REFERENCES emailbison_leads(id) ON DELETE CASCADE,
    emails_sent INTEGER NOT NULL DEFAULT 0,
    opens INTEGER NOT NULL DEFAULT 0,
    replies INTEGER NOT NULL DEFAULT 0,
    last_sent_date TIMESTAMPTZ,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (contact_id, campaign_id)
);

CREATE INDEX idx_contact_campaigns_campaign ON contact_campaigns(campaign_id);
CREATE INDEX idx_contact_campaigns_lead ON contact_campaigns(lead_id);
CREATE INDEX idx_contact_campaigns_stats ON contact_campaigns(campaign_id, emails_sent, opens, replies);

-- +goose Down
DROP INDEX IF EXISTS idx_contact_campaigns_stats;
DROP INDEX IF EXISTS idx_contact_campaigns_lead;
DROP INDEX IF EXISTS idx_contact_campaigns_campaign;
DROP TABLE IF EXISTS contact_campaigns;
DROP INDEX IF EXISTS idx_emailbison_leads_status;
DROP INDEX IF EXISTS idx_emailbison_leads_contact;
DROP TABLE IF EXISTS emailbison_leads;
DROP INDEX IF EXISTS idx_campaigns_last_sync;
DROP INDEX IF EXISTS idx_campaigns_status;
DROP TABLE IF EXISTS campaigns;
