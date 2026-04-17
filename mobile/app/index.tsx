import { Audio } from "expo-av";
import { StatusBar } from "expo-status-bar";
import { useMemo, useState } from "react";
import { ActivityIndicator, Alert, Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View } from "react-native";
import {
  checkHealth,
  createSheetFromTranscript,
  getNote,
  listNotes,
  type NoteDetail,
  type NoteSummary,
  type TranscribeResponse,
  uploadAudio
} from "../src/api";
import { API_BASE } from "../src/config";

type RecordingState = Audio.Recording | null;

export default function HomeScreen() {
  const [recording, setRecording] = useState<RecordingState>(null);
  const [isBusy, setIsBusy] = useState(false);
  const [statusText, setStatusText] = useState("Pret");
  const [lastTranscribe, setLastTranscribe] = useState<TranscribeResponse | null>(null);
  const [notes, setNotes] = useState<NoteSummary[]>([]);
  const [selectedNote, setSelectedNote] = useState<NoteDetail | null>(null);

  const isRecording = useMemo(() => recording !== null, [recording]);

  async function onCheckHealth() {
    setIsBusy(true);
    setStatusText("Verification backend...");
    try {
      const health = await checkHealth();
      setStatusText(health.ok ? "Backend en ligne" : "Backend indisponible");
    } catch (error) {
      setStatusText("Backend indisponible");
      Alert.alert("Erreur reseau", String(error));
    } finally {
      setIsBusy(false);
    }
  }

  async function startRecording() {
    try {
      setStatusText("Demande permission micro...");
      const permission = await Audio.requestPermissionsAsync();
      if (permission.status !== "granted") {
        Alert.alert("Permission requise", "Autorisez le microphone pour enregistrer.");
        setStatusText("Permission micro refusee");
        return;
      }

      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true
      });

      const newRecording = new Audio.Recording();
      await newRecording.prepareToRecordAsync(Audio.RecordingOptionsPresets.HIGH_QUALITY);
      await newRecording.startAsync();
      setRecording(newRecording);
      setStatusText("Enregistrement en cours...");
    } catch (error) {
      Alert.alert("Erreur", `Impossible de demarrer l'enregistrement: ${String(error)}`);
      setStatusText("Echec demarrage enregistrement");
    }
  }

  async function stopAndUploadRecording() {
    if (!recording) {
      return;
    }

    setIsBusy(true);
    setStatusText("Arret enregistrement...");

    try {
      await recording.stopAndUnloadAsync();
      const uri = recording.getURI();
      setRecording(null);

      if (!uri) {
        throw new Error("URI d'enregistrement introuvable.");
      }

      setStatusText("Upload et transcription...");
      const response = await uploadAudio(uri);
      setStatusText("Transcription terminee");
      setLastTranscribe(response);
      await refreshNotes();
    } catch (error) {
      setStatusText("Erreur pendant upload/transcription");
      Alert.alert("Erreur", String(error));
    } finally {
      setIsBusy(false);
    }
  }

  async function refreshNotes() {
    setIsBusy(true);
    setStatusText("Chargement de l'historique...");
    try {
      const data = await listNotes();
      setNotes(data);
      setStatusText(`${data.length} note(s) chargee(s)`);
    } catch (error) {
      setStatusText("Echec chargement historique");
      Alert.alert("Erreur", String(error));
    } finally {
      setIsBusy(false);
    }
  }

  async function openNote(noteId: string) {
    setIsBusy(true);
    setStatusText("Chargement de la note...");
    try {
      const note = await getNote(noteId);
      setSelectedNote(note);
      setStatusText("Note chargee");
    } catch (error) {
      setStatusText("Echec ouverture note");
      Alert.alert("Erreur", String(error));
    } finally {
      setIsBusy(false);
    }
  }

  async function generateSheetFromLast() {
    if (!lastTranscribe) {
      Alert.alert("Aucune transcription", "Enregistre d'abord une note audio.");
      return;
    }
    setIsBusy(true);
    setStatusText("Generation fiche medicale...");
    try {
      const sheet = await createSheetFromTranscript(lastTranscribe.id, lastTranscribe.transcript);
      setStatusText(`Fiche creee: ${sheet.id}`);
      Alert.alert("Fiche creee", `Fiche medicale generee avec succes (${sheet.id}).`);
    } catch (error) {
      setStatusText("Echec generation fiche");
      Alert.alert("Erreur", String(error));
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="auto" />
      <View style={styles.header}>
        <Text style={styles.title}>MedNote Mobile</Text>
        <Text style={styles.subtitle}>API: {API_BASE}</Text>
      </View>

      <View style={styles.controls}>
        <Pressable
          style={[styles.button, styles.secondaryButton, isBusy && styles.buttonDisabled]}
          onPress={onCheckHealth}
          disabled={isBusy}
        >
          <Text style={styles.buttonText}>Tester /health</Text>
        </Pressable>
        <Pressable
          style={[styles.button, styles.secondaryButton, isBusy && styles.buttonDisabled]}
          onPress={refreshNotes}
          disabled={isBusy}
        >
          <Text style={styles.buttonText}>Rafraichir historique</Text>
        </Pressable>

        {!isRecording ? (
          <Pressable
            style={[styles.button, styles.primaryButton, isBusy && styles.buttonDisabled]}
            onPress={startRecording}
            disabled={isBusy}
          >
            <Text style={styles.buttonText}>Demarrer enregistrement</Text>
          </Pressable>
        ) : (
          <Pressable
            style={[styles.button, styles.stopButton, isBusy && styles.buttonDisabled]}
            onPress={stopAndUploadRecording}
            disabled={isBusy}
          >
            <Text style={styles.buttonText}>Arreter et envoyer</Text>
          </Pressable>
        )}
        <Pressable
          style={[styles.button, styles.primaryButton, isBusy && styles.buttonDisabled]}
          onPress={generateSheetFromLast}
          disabled={isBusy}
        >
          <Text style={styles.buttonText}>Generer fiche depuis la derniere transcription</Text>
        </Pressable>
      </View>

      <View style={styles.statusRow}>
        {isBusy && <ActivityIndicator size="small" color="#2563eb" />}
        <Text style={styles.statusText}>{statusText}</Text>
      </View>

      <ScrollView style={styles.output} contentContainerStyle={styles.outputContent}>
        <Text style={styles.outputTitle}>Derniere transcription</Text>
        {lastTranscribe ? (
          <>
            <Text style={styles.sectionTitle}>Motif</Text>
            <Text style={styles.outputText}>{lastTranscribe.structured.motif || "(Vide)"}</Text>
            <Text style={styles.sectionTitle}>Transcript</Text>
            <Text style={styles.outputText}>{lastTranscribe.transcript || "(Vide)"}</Text>
          </>
        ) : (
          <Text style={styles.outputText}>Aucun resultat pour le moment.</Text>
        )}

        <Text style={styles.outputTitle}>Historique des notes</Text>
        {notes.length === 0 ? (
          <Text style={styles.outputText}>Aucune note pour le moment.</Text>
        ) : (
          notes.map((note) => (
            <Pressable key={note.id} style={styles.noteCard} onPress={() => openNote(note.id)}>
              <Text style={styles.noteTitle}>{note.motif || "(Sans motif)"}</Text>
              <Text style={styles.noteMeta}>{note.created_at}</Text>
              <Text style={styles.noteMeta}>{note.id}</Text>
            </Pressable>
          ))
        )}

        <Text style={styles.outputTitle}>Detail note selectionnee</Text>
        {selectedNote ? (
          <>
            <Text style={styles.sectionTitle}>ID</Text>
            <Text style={styles.outputText}>{selectedNote.id}</Text>
            <Text style={styles.sectionTitle}>Motif</Text>
            <Text style={styles.outputText}>{selectedNote.structured.motif || "(Vide)"}</Text>
            <Text style={styles.sectionTitle}>Histoire de la maladie</Text>
            <Text style={styles.outputText}>{selectedNote.structured.histoire_maladie || "(Vide)"}</Text>
            <Text style={styles.sectionTitle}>Plan</Text>
            <Text style={styles.outputText}>{selectedNote.structured.plan || "(Vide)"}</Text>
          </>
        ) : (
          <Text style={styles.outputText}>Appuie sur une note pour afficher son detail.</Text>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#f8fafc",
    padding: 16
  },
  header: {
    marginBottom: 16
  },
  title: {
    fontSize: 26,
    fontWeight: "700",
    color: "#0f172a"
  },
  subtitle: {
    marginTop: 6,
    color: "#334155"
  },
  controls: {
    gap: 10
  },
  button: {
    borderRadius: 10,
    paddingVertical: 13,
    paddingHorizontal: 14
  },
  primaryButton: {
    backgroundColor: "#2563eb"
  },
  secondaryButton: {
    backgroundColor: "#0f766e"
  },
  stopButton: {
    backgroundColor: "#b91c1c"
  },
  buttonText: {
    color: "#ffffff",
    textAlign: "center",
    fontWeight: "600"
  },
  buttonDisabled: {
    opacity: 0.6
  },
  statusRow: {
    marginTop: 16,
    flexDirection: "row",
    alignItems: "center",
    gap: 8
  },
  statusText: {
    color: "#1e293b",
    fontWeight: "500"
  },
  output: {
    marginTop: 16,
    borderWidth: 1,
    borderColor: "#cbd5e1",
    borderRadius: 10,
    backgroundColor: "#ffffff",
    flex: 1
  },
  outputContent: {
    padding: 12
  },
  outputTitle: {
    fontWeight: "700",
    marginTop: 14,
    marginBottom: 8,
    color: "#0f172a"
  },
  sectionTitle: {
    marginTop: 8,
    marginBottom: 4,
    fontWeight: "700",
    color: "#334155"
  },
  outputText: {
    color: "#1e293b"
  },
  noteCard: {
    borderWidth: 1,
    borderColor: "#e2e8f0",
    borderRadius: 8,
    padding: 10,
    marginBottom: 8
  },
  noteTitle: {
    color: "#0f172a",
    fontWeight: "700"
  },
  noteMeta: {
    color: "#475569",
    marginTop: 2,
    fontSize: 12
  }
});
