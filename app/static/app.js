function mailDesk() {
  const initial = JSON.parse(document.getElementById('initial-state').textContent)

  return {
    acceptedDomains: initial.acceptedDomains || ['axione.xyz'],
    pollSeconds: initial.pollSeconds,
    currentUser: initial.currentUser,
    adminUsername: initial.adminUsername || 'admin',
    search: '',
    composeOpen: false,
    composeError: '',
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
    filter: { mode: 'primary' },
    auth: { user: initial.currentUser, mode: 'login', message: '', error: '', form: { username: '', password: '' } },
    form: { localPart: '', domain: (initial.acceptedDomains || ['axione.xyz'])[0] || 'axione.xyz', isPersistent: false, profileName: '', inboxMode: 'temp' },

    async init() {
      await this.loadMe()
      if (this.auth.user) {
        this.ensureValidDomain()
        await this.fetchInboxes()
        if (this.auth.user.is_admin) {
          await this.loadPendingUsers()
          await this.loadPendingPersonalInboxes()
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
        if (this.auth.user && this.auth.user.is_admin) await this.loadPendingUsers()
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
      this.selectedMessage = null
      this.selectedMessageDetail = null
      this.composeOpen = false
      this.setNotice('Cikis yapildi', 'success')
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
      this.activeInbox = this.inboxes.find((item) => item.address === address) || await this.api(`/api/inboxes/${encodeURIComponent(address)}`)
      await this.refreshMessages()
    },

    async refreshMessages() {
      if (!this.activeInbox || !this.auth.user) return
      this.messages = await this.api(`/api/inboxes/${encodeURIComponent(this.activeInbox.address)}/messages`)
      await this.fetchInboxes()
      if (!this.messages.length) {
        this.selectedMessage = null
        this.selectedMessageDetail = null
        this.messageViewOpen = false
        return
      }
      const currentId = this.selectedMessage?.id
      const nextMessage = this.messages.find((item) => item.id === currentId) || this.filteredMessages()[0] || this.messages[0]
      if (nextMessage) await this.loadMessage(nextMessage.id)
    },

    async loadMessage(messageId) {
      this.selectedMessageDetail = await this.api(`/api/messages/${messageId}`)
      this.selectedMessage = this.messages.find((item) => item.id === messageId) || this.selectedMessageDetail
      this.messageViewOpen = true
      if (this.selectedMessage) this.selectedMessage.is_unread = false
      await this.fetchInboxes()
    },

    closeMessageView() {
      this.messageViewOpen = false
    },

    async togglePersistent() {
      if (!this.activeInbox) return
      const updated = await this.api(`/api/inboxes/${encodeURIComponent(this.activeInbox.address)}`, { method: 'PATCH', body: JSON.stringify({ is_persistent: !this.activeInbox.is_persistent }) })
      this.activeInbox = updated
      await this.fetchInboxes()
    },

    async toggleSelectedUnread() {
      if (!this.selectedMessage) return
      const updated = await this.api(`/api/messages/${this.selectedMessage.id}`, { method: 'PATCH', body: JSON.stringify({ is_unread: !this.selectedMessage.is_unread }) })
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
      if (this.filter.mode === 'social') items = items.filter((m) => m.message_category === 'social')
      if (this.filter.mode === 'spam') items = items.filter((m) => m.message_category === 'spam')
      if (this.filter.mode === 'updates') items = items.filter((m) => m.message_category === 'updates')
      if (this.filter.mode === 'primary') items = items.filter((m) => m.message_category === 'primary')
      if (this.filter.mode === 'verification') items = items.filter((m) => ['verification', 'password_reset', 'login_link', 'code'].includes(m.message_kind))
      if (this.search.trim()) {
        const q = this.search.trim().toLowerCase()
        items = items.filter((m) => [m.subject, m.mail_from, m.sender_domain, m.summary].join(' ').toLowerCase().includes(q))
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
      const local = this.form.localPart?.trim() || 'otomatik-uretilecek'
      const domain = this.form.domain || this.acceptedDomains[0] || 'axione.xyz'
      return `${local}@${domain}`
    },

    inboxBadge(inbox) {
      if (!inbox) return ''
      if (inbox.inbox_mode === 'personal') return inbox.is_approved ? 'Kisisel' : 'Kisisel Onay'
      return 'Temp 5 dk'
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

    clearNotice() {
      this.notice = { text: '', type: 'success' }
    },
  }
}
