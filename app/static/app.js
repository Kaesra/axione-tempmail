function mailDesk() {
  const initial = JSON.parse(document.getElementById('initial-state').textContent)

  return {
    acceptedDomains: initial.acceptedDomains || ['axione.xyz'],
    pollSeconds: initial.pollSeconds,
    tempInboxMinutes: initial.tempInboxMinutes || 5,
    tempDailyLimit: initial.tempDailyLimit || 3,
    currentUser: initial.currentUser,
    adminUsername: initial.adminUsername || 'admin',
    search: '',
    composeOpen: false,
    accountOpen: false,
    adminMonitorOpen: false,
    composeError: '',
    apiKeyError: '',
    adminMonitorError: '',
    notice: { text: '', type: 'success' },
    inboxes: [],
    messages: [],
    activeInbox: null,
    selectedMessage: null,
    selectedMessageDetail: null,
    messageViewOpen: false,
    poller: null,
    pendingUsers: [],
    pendingPersonalInboxes: [],
    apiKeys: [],
    adminInboxes: [],
    adminMessages: [],
    adminSelectedMessage: null,
    filter: { mode: 'all' },
    auth: { user: initial.currentUser, mode: 'login', message: '', error: '', form: { username: '', password: '' } },
    form: { localPart: '', domain: (initial.acceptedDomains || ['axione.xyz'])[0] || 'axione.xyz', isPersistent: false, profileName: '', inboxMode: 'temp' },
    apiKeyForm: { name: '' },

    async init() {
      await this.loadMe()
      if (this.auth.user) {
        this.ensureValidDomain()
        await this.fetchInboxes()
        await this.loadApiKeys()
        if (this.auth.user.is_admin) {
          await this.loadPendingUsers()
          await this.loadPendingPersonalInboxes()
          await this.loadAdminOverview()
        }
      }
      this.startPolling()
    },

    ensureValidDomain() {
      if (!this.acceptedDomains.length) this.acceptedDomains = ['axione.xyz']
      if (!this.acceptedDomains.includes(this.form.domain)) this.form.domain = this.acceptedDomains[0]
    },

    async api(url, options = {}) {
      const response = await fetch(url, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options })
      if (!response.ok) {
        let message = 'Istek basarisiz'
        try {
          const payload = await response.json()
          const candidate = payload.detail || payload.message || payload
          message = this.normalizeError(candidate)
        } catch {
          message = this.normalizeError(await response.text() || message)
        }
        if (response.status === 401) this.auth.user = null
        throw new Error(message)
      }
      if (response.status === 204) return null
      const contentType = response.headers.get('content-type') || ''
      return contentType.includes('application/json') ? response.json() : response.text()
    },

    async loadMe() {
      try {
        const payload = await this.api('/api/auth/me')
        this.auth.user = payload.user
      } catch {
        this.auth.user = null
      }
    },

    async register() {
      this.auth.error = ''
      this.auth.message = ''
      try {
        const payload = await this.api('/api/auth/register', { method: 'POST', body: JSON.stringify(this.auth.form) })
        this.auth.message = payload.message
        this.setNotice(payload.message, 'success')
        this.auth.mode = 'login'
      } catch (error) {
        this.auth.error = error.message
        this.setNotice(error.message, 'error')
      }
    },

    async login() {
      this.auth.error = ''
      this.auth.message = ''
      try {
        const payload = await this.api('/api/auth/login', { method: 'POST', body: JSON.stringify(this.auth.form) })
        this.auth.user = payload.user
        this.auth.form.password = ''
        this.ensureValidDomain()
        this.setNotice(`Hos geldin ${payload.user.username}`, 'success')
        await this.fetchInboxes()
        await this.loadApiKeys()
        if (this.auth.user && this.auth.user.is_admin) {
          await this.loadPendingUsers()
          await this.loadPendingPersonalInboxes()
          await this.loadAdminOverview()
        }
      } catch (error) {
        this.auth.error = error.message
        this.setNotice(error.message, 'error')
      }
    },

    async logout() {
      await this.api('/api/auth/logout', { method: 'POST' })
      this.auth.user = null
      this.inboxes = []
      this.messages = []
      this.apiKeys = []
      this.adminInboxes = []
      this.adminMessages = []
      this.adminSelectedMessage = null
      this.selectedMessage = null
      this.selectedMessageDetail = null
      this.composeOpen = false
      this.accountOpen = false
      this.adminMonitorOpen = false
      this.setNotice('Cikis yapildi', 'success')
    },

    async loadApiKeys() {
      if (!this.auth.user) return
      this.apiKeys = await this.api('/api/auth/api-keys')
    },

    openAccount() {
      if (!this.auth.user) return
      this.accountOpen = true
      this.apiKeyError = ''
      this.loadApiKeys()
    },

    closeAccount() {
      this.accountOpen = false
      this.apiKeyError = ''
      this.apiKeyForm.name = ''
    },

    async createApiKey() {
      this.apiKeyError = ''
      try {
        const payload = await this.api('/api/auth/api-keys', { method: 'POST', body: JSON.stringify(this.apiKeyForm) })
        this.apiKeyForm.name = ''
        this.apiKeys = [payload.api_key, ...this.apiKeys]
        this.setNotice('API key olusturuldu', 'success')
      } catch (error) {
        this.apiKeyError = error.message
        this.setNotice(error.message, 'error')
      }
    },

    async revokeApiKey(apiKeyId) {
      try {
        const updated = await this.api(`/api/auth/api-keys/${apiKeyId}`, { method: 'DELETE' })
        const index = this.apiKeys.findIndex((item) => item.id === updated.id)
        if (index >= 0) this.apiKeys[index] = updated
        this.setNotice('API key iptal edildi', 'success')
      } catch (error) {
        this.apiKeyError = error.message
        this.setNotice(error.message, 'error')
      }
    },

    async loadPendingUsers() {
      if (!this.auth.user || !this.auth.user.is_admin) return
      this.pendingUsers = await this.api('/api/admin/users')
    },

    async loadPendingPersonalInboxes() {
      if (!this.auth.user || !this.auth.user.is_admin) return
      this.pendingPersonalInboxes = await this.api('/api/admin/inboxes/pending-personal')
    },

    async approveUser(userId) {
      await this.api(`/api/admin/users/${userId}/approve`, { method: 'POST' })
      this.setNotice('Kullanici onaylandi', 'success')
      await this.loadPendingUsers()
    },

    async approvePersonalInbox(inboxId) {
      await this.api(`/api/admin/inboxes/${inboxId}/approve-personal`, { method: 'POST' })
      this.setNotice('Kisisel inbox onaylandi', 'success')
      await this.loadPendingPersonalInboxes()
      await this.fetchInboxes()
    },

    async loadAdminOverview() {
      if (!this.auth.user || !this.auth.user.is_admin) return
      this.adminInboxes = await this.api('/api/admin/inboxes/all')
      this.adminMessages = await this.api('/api/admin/messages/recent')
    },

    openAdminMonitor() {
      if (!this.auth.user || !this.auth.user.is_admin) return
      this.adminMonitorOpen = true
      this.adminMonitorError = ''
      this.loadAdminOverview()
    },

    closeAdminMonitor() {
      this.adminMonitorOpen = false
      this.adminMonitorError = ''
      this.adminSelectedMessage = null
    },

    async loadAdminMessage(messageId) {
      this.adminMonitorError = ''
      try {
        this.adminSelectedMessage = this.normalizeMessage(await this.api(`/api/admin/messages/${messageId}`))
      } catch (error) {
        this.adminMonitorError = error.message
        this.setNotice(error.message, 'error')
      }
    },

    async deleteAdminMessage(messageId) {
      this.adminMonitorError = ''
      try {
        await this.api(`/api/admin/messages/${messageId}`, { method: 'DELETE' })
        this.adminMessages = this.adminMessages.filter((item) => item.id !== messageId)
        if (this.adminSelectedMessage && this.adminSelectedMessage.id === messageId) this.adminSelectedMessage = null
        this.setNotice('Admin mesaj kaydi silindi', 'success')
        await this.loadAdminOverview()
      } catch (error) {
        this.adminMonitorError = error.message
        this.setNotice(error.message, 'error')
      }
    },

    async fetchInboxes() {
      if (!this.auth.user) return
      this.inboxes = await this.api('/api/inboxes')
      if (!this.activeInbox && this.inboxes[0]) await this.selectInbox(this.inboxes[0].address)
      else if (this.activeInbox) {
        const fresh = this.inboxes.find((item) => item.address === this.activeInbox.address)
        if (fresh) this.activeInbox = fresh
      }
    },

    async createInbox() {
      this.ensureValidDomain()
      this.composeError = ''
      try {
        const inbox = await this.api('/api/inboxes', {
          method: 'POST',
          body: JSON.stringify({
            local_part: this.form.localPart || null,
            domain: this.form.domain || null,
            is_persistent: this.form.isPersistent || this.form.inboxMode === 'personal',
            profile_name: this.form.profileName || null,
            inbox_mode: this.form.inboxMode,
          }),
        })
        this.form.localPart = ''
        this.form.profileName = ''
        this.form.inboxMode = 'temp'
        this.form.isPersistent = false
        this.composeOpen = false
        this.setNotice(inbox.inbox_mode === 'personal' ? `Kisisel inbox talebi olusturuldu: ${inbox.address}` : `Temp inbox olusturuldu: ${inbox.address}`, 'success')
        await this.fetchInboxes()
        await this.selectInbox(inbox.address)
      } catch (error) {
        this.composeError = error.message
        this.setNotice(error.message, 'error')
      }
    },

    async selectInbox(address) {
      this.messageViewOpen = false
      this.activeInbox = this.inboxes.find((item) => item.address === address) || await this.api(`/api/inboxes/${encodeURIComponent(address)}`)
      await this.refreshMessages()
    },

    async refreshMessages() {
      if (!this.activeInbox || !this.auth.user) return
      const payload = await this.api(`/api/inboxes/${encodeURIComponent(this.activeInbox.address)}/messages`)
      this.messages = Array.isArray(payload) ? payload.map((item) => this.normalizeMessage(item)) : []
      await this.fetchInboxes()
      if (!this.messages.length) {
        this.selectedMessage = null
        this.selectedMessageDetail = null
        this.messageViewOpen = false
        return
      }
      const currentId = this.selectedMessage?.id
      if (currentId && this.messageViewOpen) {
        const nextMessage = this.messages.find((item) => item.id === currentId)
        if (nextMessage) await this.loadMessage(nextMessage.id)
        else {
          this.selectedMessage = null
          this.selectedMessageDetail = null
          this.messageViewOpen = false
        }
      }
    },

    async loadMessage(messageId) {
      this.selectedMessageDetail = this.normalizeMessage(await this.api(`/api/messages/${messageId}`))
      this.selectedMessage = this.messages.find((item) => item.id === messageId) || this.selectedMessageDetail
      this.messageViewOpen = true
      if (this.selectedMessage) this.selectedMessage.is_unread = false
      await this.fetchInboxes()
    },

    closeMessageView() {
      this.messageViewOpen = false
      this.selectedMessageDetail = null
    },

    async togglePersistent() {
      if (!this.activeInbox) return
      const updated = await this.api(`/api/inboxes/${encodeURIComponent(this.activeInbox.address)}`, { method: 'PATCH', body: JSON.stringify({ is_persistent: !this.activeInbox.is_persistent }) })
      this.activeInbox = updated
      await this.fetchInboxes()
    },

    async toggleSelectedUnread() {
      if (!this.selectedMessage) return
      const updated = this.normalizeMessage(await this.api(`/api/messages/${this.selectedMessage.id}`, { method: 'PATCH', body: JSON.stringify({ is_unread: !this.selectedMessage.is_unread }) }))
      const index = this.messages.findIndex((item) => item.id === updated.id)
      if (index >= 0) this.messages[index] = { ...this.messages[index], ...updated }
      this.selectedMessage = { ...(this.selectedMessage || {}), ...updated }
      if (this.selectedMessageDetail) this.selectedMessageDetail.is_unread = updated.is_unread
      await this.fetchInboxes()
    },

    async purgeInbox() {
      if (!this.activeInbox) return
      await this.api(`/api/inboxes/${encodeURIComponent(this.activeInbox.address)}/messages`, { method: 'DELETE' })
      await this.refreshMessages()
    },

    async deleteSelectedMessage() {
      if (!this.selectedMessage) return
      await this.api(`/api/messages/${this.selectedMessage.id}`, { method: 'DELETE' })
      await this.refreshMessages()
    },

    filteredMessages() {
      let items = this.messages
      if (this.filter.mode === 'all') items = items
      if (this.filter.mode === 'social') items = items.filter((m) => m.message_category === 'social')
      if (this.filter.mode === 'spam') items = items.filter((m) => m.message_category === 'spam')
      if (this.filter.mode === 'updates') items = items.filter((m) => m.message_category === 'updates')
      if (this.filter.mode === 'primary') items = items.filter((m) => m.message_category === 'primary')
      if (this.filter.mode === 'verification') items = items.filter((m) => ['verification', 'password_reset', 'login_link', 'code'].includes(m.message_kind))
      if (this.search.trim()) {
        const q = this.search.trim().toLowerCase()
        items = items.filter((m) => [m.subject || '', m.mail_from || '', m.sender_domain || '', m.summary || ''].join(' ').toLowerCase().includes(q))
      }
      return items
    },

    totalUnread() {
      return this.inboxes.reduce((sum, inbox) => sum + (inbox.unread_count || 0), 0)
    },

    logoSubtitle(inbox) {
      if (!inbox) return ''
      if (inbox.inbox_mode === 'personal') return inbox.is_approved ? 'Kisisel' : 'Onay Bekliyor'
      return inbox.expires_at ? `5 dk temp` : 'Temp'
    },

    startPolling() {
      clearInterval(this.poller)
      this.poller = setInterval(() => {
        if (this.activeInbox && this.auth.user) this.refreshMessages()
        if (this.auth.user && this.auth.user.is_admin) {
          this.loadPendingUsers()
          this.loadPendingPersonalInboxes()
          this.loadAdminOverview()
        }
      }, this.pollSeconds * 1000)
    },

    copyText(value) {
      navigator.clipboard.writeText(value)
    },

    openLink(value) {
      window.open(value, '_blank', 'noopener,noreferrer')
    },

    formatDate(value) {
      if (!value) return '-'
      return new Date(value).toLocaleDateString('tr-TR', { day: '2-digit', month: 'short' })
    },

    formatDateTime(value) {
      if (!value) return '-'
      return new Date(value).toLocaleString('tr-TR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
    },

    messageCounterLabel() {
      const total = this.filteredMessages().length
      return total ? `1-${Math.min(total, 50)} / ${total}` : '0 mesaj'
    },

    previewInboxAddress() {
      const local = this.form.inboxMode === 'temp' ? 'otomatik-uretilecek' : (this.form.localPart?.trim() || 'otomatik-uretilecek')
      const domain = this.form.domain || this.acceptedDomains[0] || 'axione.xyz'
      return `${local}@${domain}`
    },

    inboxBadge(inbox) {
      if (!inbox) return ''
      if (inbox.inbox_mode === 'personal') return inbox.is_approved ? 'Kisisel' : 'Kisisel Onay'
      return 'Temp 5 dk'
    },

    apiKeyMask(apiKey) {
      if (!apiKey) return ''
      return `${apiKey.prefix || 'axm'}...${apiKey.last_four || ''}`
    },

    setNotice(text, type = 'success') {
      this.notice = { text, type }
    },

    normalizeError(value) {
      if (typeof value === 'string') return value
      if (Array.isArray(value)) return value.map((item) => this.normalizeError(item)).join(', ')
      if (value && typeof value === 'object') {
        if (typeof value.msg === 'string') return value.msg
        if (typeof value.message === 'string') return value.message
        if (typeof value.detail === 'string') return value.detail
        return JSON.stringify(value)
      }
      return String(value || 'Istek basarisiz')
    },

    normalizeMessage(value) {
      const message = value && typeof value === 'object' ? { ...value } : {}
      message.codes = Array.isArray(message.codes) ? message.codes.filter((item) => typeof item === 'string' && item.trim()) : []
      message.mail_from = typeof message.mail_from === 'string' ? message.mail_from : ''
      message.sender_domain = typeof message.sender_domain === 'string' ? message.sender_domain : ''
      message.subject = typeof message.subject === 'string' ? message.subject : ''
      message.summary = typeof message.summary === 'string' ? message.summary : ''
      message.message_category = typeof message.message_category === 'string' ? message.message_category : 'primary'
      message.message_kind = typeof message.message_kind === 'string' ? message.message_kind : 'general'
      message.verification_link = typeof message.verification_link === 'string' ? message.verification_link : ''
      message.text_body = typeof message.text_body === 'string' ? message.text_body : ''
      message.html_body = typeof message.html_body === 'string' ? message.html_body : ''
      message.raw_headers = typeof message.raw_headers === 'string' ? message.raw_headers : ''
      message.is_unread = Boolean(message.is_unread)
      message.owner_username = typeof message.owner_username === 'string' ? message.owner_username : ''
      message.inbox_profile_name = typeof message.inbox_profile_name === 'string' ? message.inbox_profile_name : ''
      return message
    },

    clearNotice() {
      this.notice = { text: '', type: 'success' }
    },
  }
}
