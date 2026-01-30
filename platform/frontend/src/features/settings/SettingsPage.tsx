import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export default function SettingsPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold mb-6">Settings</h1>
      <Card>
        <CardHeader><CardTitle>General</CardTitle></CardHeader>
        <CardContent>
          <p className="text-muted-foreground">Settings page coming soon.</p>
        </CardContent>
      </Card>
    </div>
  )
}
